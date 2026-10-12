//go:build windows

// AgentZero.exe - the launcher for an installed Agent Zero for Windows.
//
// It lives in the install folder (setup puts it there) so Task Manager and
// the taskbar show "AgentZero.exe" instead of pythonw.exe. It:
//   - starts the server hidden (.venv\Scripts\python.exe run_ui.py) unless
//     something already answers on the web UI port,
//   - shows a tray icon: left click opens Agent Zero in the browser; the
//     right-click menu has Open, Settings and Quit,
//   - Quit stops the server it started together with everything the server
//     started (the tunnel, a managed llama.cpp server), so nothing is left behind,
//   - allows one copy: starting it again just opens the browser.
//
// Standard library only. Windows subsystem "gui" (no console window).
package main

import (
	_ "embed"
	"encoding/binary"
	"flag"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

//go:embed assets/agent-zero.ico
var iconFile []byte

const (
	appName     = "Agent Zero"
	defaultPort = 5000

	wmDestroy   = 0x0002
	wmClose     = 0x0010
	wmCommand   = 0x0111
	wmUser      = 0x0400
	wmLButtonUp = 0x0202
	wmRButtonUp = 0x0205
	wmTray      = wmUser + 20

	nimAdd, nimDelete          = 0, 2
	nifMessage, nifIcon, nifTip = 0x1, 0x2, 0x4
	tpmRightButton              = 0x0002
	tpmBottomAlign              = 0x0020
	mfString, mfSeparator       = 0x0, 0x800
	idiApplication              = 32512

	menuOpen, menuSettings, menuQuit = 1, 2, 3
	createNoWindow                   = 0x08000000
	errorAlreadyExists               = 183
)

var (
	user32   = syscall.NewLazyDLL("user32.dll")
	shell32  = syscall.NewLazyDLL("shell32.dll")
	kernel32 = syscall.NewLazyDLL("kernel32.dll")

	pRegisterClass   = user32.NewProc("RegisterClassW")
	pCreateWindowEx  = user32.NewProc("CreateWindowExW")
	pDefWindowProc   = user32.NewProc("DefWindowProcW")
	pGetMessage      = user32.NewProc("GetMessageW")
	pTranslate       = user32.NewProc("TranslateMessage")
	pDispatch        = user32.NewProc("DispatchMessageW")
	pPostQuit        = user32.NewProc("PostQuitMessage")
	pPostMessage     = user32.NewProc("PostMessageW")
	pDestroyWindow   = user32.NewProc("DestroyWindow")
	pCreatePopupMenu = user32.NewProc("CreatePopupMenu")
	pAppendMenu      = user32.NewProc("AppendMenuW")
	pTrackPopupMenu  = user32.NewProc("TrackPopupMenu")
	pDestroyMenu     = user32.NewProc("DestroyMenu")
	pGetCursorPos    = user32.NewProc("GetCursorPos")
	pSetForeground   = user32.NewProc("SetForegroundWindow")
	pLoadIcon        = user32.NewProc("LoadIconW")
	pCreateIconFrom  = user32.NewProc("CreateIconFromResourceEx")
	pNotifyIcon      = shell32.NewProc("Shell_NotifyIconW")
	pShellExecute    = shell32.NewProc("ShellExecuteW")
	pGetModuleHandle = kernel32.NewProc("GetModuleHandleW")
	pCreateMutex     = kernel32.NewProc("CreateMutexW")
)

type wndClass struct {
	style         uint32
	wndProc       uintptr
	clsExtra      int32
	wndExtra      int32
	instance      syscall.Handle
	icon          syscall.Handle
	cursor        syscall.Handle
	background    syscall.Handle
	menuName      *uint16
	className     *uint16
}

type point struct{ x, y int32 }

type msg struct {
	hwnd    syscall.Handle
	message uint32
	wParam  uintptr
	lParam  uintptr
	time    uint32
	pt      point
}

type notifyIconData struct {
	size            uint32
	hwnd            syscall.Handle
	id              uint32
	flags           uint32
	callbackMessage uint32
	icon            syscall.Handle
	tip             [128]uint16
	state           uint32
	stateMask       uint32
	info            [256]uint16
	version         uint32
	infoTitle       [64]uint16
	infoFlags       uint32
	guid            [16]byte
	balloonIcon     syscall.Handle
}

var (
	root   string
	port   int
	server *os.Process
	hwnd   syscall.Handle
	nid    notifyIconData
)

func utf16(s string) *uint16 {
	p, _ := syscall.UTF16PtrFromString(s)
	return p
}

// installRoot is the folder AgentZero.exe lives in.
func installRoot() string {
	exe, err := os.Executable()
	if err != nil {
		return "."
	}
	return filepath.Dir(exe)
}

func webUIPort() int {
	data, err := os.ReadFile(filepath.Join(root, "usr", ".env"))
	if err == nil {
		for _, line := range strings.Split(string(data), "\n") {
			key, value, ok := strings.Cut(strings.TrimSpace(line), "=")
			if ok && strings.TrimSpace(key) == "WEB_UI_PORT" {
				if n, err := strconv.Atoi(strings.Trim(strings.TrimSpace(value), `"'`)); err == nil && n > 0 {
					return n
				}
			}
		}
	}
	return defaultPort
}

func answers(p int) bool {
	conn, err := net.DialTimeout("tcp", "127.0.0.1:"+strconv.Itoa(p), time.Second)
	if err != nil {
		return false
	}
	conn.Close()
	return true
}

func openBrowser(path string) {
	url := "http://localhost:" + strconv.Itoa(port) + "/" + path
	pShellExecute.Call(0, uintptr(unsafe.Pointer(utf16("open"))), uintptr(unsafe.Pointer(utf16(url))), 0, 0, 1)
}

func pythonExe() string {
	venv := filepath.Join(root, ".venv", "Scripts", "python.exe")
	if _, err := os.Stat(venv); err == nil {
		return venv
	}
	return "python.exe"
}

func openLog() *os.File {
	logDir := filepath.Join(root, "logs")
	_ = os.MkdirAll(logDir, 0o755)
	path := filepath.Join(logDir, "launcher.log")
	if st, err := os.Stat(path); err == nil && st.Size() > 5*1024*1024 {
		_ = os.Rename(path, path+".1")
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return nil
	}
	return f
}

func startServer() {
	if answers(port) {
		return // already running (for example started by "Start at logon")
	}
	log := openLog()
	if log != nil {
		fmt.Fprintf(log, "[%s] launcher: starting Agent Zero on port %d\n", time.Now().Format("2006-01-02 15:04:05"), port)
	}
	cmd := exec.Command(pythonExe(), "run_ui.py")
	cmd.Dir = root
	cmd.Stdout, cmd.Stderr = log, log
	cmd.Env = append(os.Environ(), "PYTHONIOENCODING=utf-8", "PYTHONUNBUFFERED=1")
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: createNoWindow}
	if err := cmd.Start(); err != nil {
		if log != nil {
			fmt.Fprintf(log, "launcher: could not start the server: %v\n", err)
		}
		return
	}
	server = cmd.Process
	go func() { _ = cmd.Wait() }()
}

// stopServer stops the server we started and everything it started.
func stopServer() {
	if server == nil {
		return
	}
	kill := exec.Command("taskkill", "/PID", strconv.Itoa(server.Pid), "/T", "/F")
	kill.SysProcAttr = &syscall.SysProcAttr{CreationFlags: createNoWindow}
	_ = kill.Run()
}

// loadIcon is the tray icon: the embedded one, or the generic application icon.
func loadIcon() syscall.Handle {
	if h := embeddedIcon(); h != 0 {
		return h
	}
	h, _, _ := pLoadIcon.Call(0, uintptr(idiApplication))
	return syscall.Handle(h)
}

// embeddedIcon builds an icon from the embedded .ico: the image closest to
// 32x32. 0 when it cannot be built.
func embeddedIcon() syscall.Handle {
	if len(iconFile) >= 6 {
		count := int(binary.LittleEndian.Uint16(iconFile[4:6]))
		best, bestScore := -1, 1<<30
		for i := 0; i < count && 6+16*(i+1) <= len(iconFile); i++ {
			entry := iconFile[6+16*i:]
			w := int(entry[0])
			if w == 0 {
				w = 256
			}
			score := abs(w - 32)
			if score < bestScore {
				best, bestScore = i, score
			}
		}
		if best >= 0 {
			entry := iconFile[6+16*best:]
			size := int(binary.LittleEndian.Uint32(entry[8:12]))
			offset := int(binary.LittleEndian.Uint32(entry[12:16]))
			w := int(entry[0])
			if w == 0 {
				w = 256
			}
			if offset+size <= len(iconFile) {
				h, _, _ := pCreateIconFrom.Call(uintptr(unsafe.Pointer(&iconFile[offset])), uintptr(size), 1, 0x00030000, uintptr(w), uintptr(w), 0)
				if h != 0 {
					return syscall.Handle(h)
				}
			}
		}
	}
	return 0
}

func abs(n int) int {
	if n < 0 {
		return -n
	}
	return n
}

func showMenu() {
	menu, _, _ := pCreatePopupMenu.Call()
	pAppendMenu.Call(menu, mfString, menuOpen, uintptr(unsafe.Pointer(utf16("Open Agent Zero"))))
	pAppendMenu.Call(menu, mfString, menuSettings, uintptr(unsafe.Pointer(utf16("Settings"))))
	pAppendMenu.Call(menu, mfSeparator, 0, 0)
	quit := "Quit"
	if server == nil {
		quit = "Close this tray icon"
	}
	pAppendMenu.Call(menu, mfString, menuQuit, uintptr(unsafe.Pointer(utf16(quit))))
	var pt point
	pGetCursorPos.Call(uintptr(unsafe.Pointer(&pt)))
	pSetForeground.Call(uintptr(hwnd))
	pTrackPopupMenu.Call(menu, tpmRightButton|tpmBottomAlign, uintptr(pt.x), uintptr(pt.y), 0, uintptr(hwnd), 0)
	pDestroyMenu.Call(menu)
}

func wndProc(h syscall.Handle, message uint32, wParam, lParam uintptr) uintptr {
	switch message {
	case wmTray:
		switch lParam {
		case wmLButtonUp:
			openBrowser("")
		case wmRButtonUp:
			showMenu()
		}
		return 0
	case wmCommand:
		switch wParam & 0xFFFF {
		case menuOpen:
			openBrowser("")
		case menuSettings:
			openBrowser("#settings")
		case menuQuit:
			stopServer()
			pDestroyWindow.Call(uintptr(h))
		}
		return 0
	case wmDestroy:
		pNotifyIcon.Call(nimDelete, uintptr(unsafe.Pointer(&nid)))
		pPostQuit.Call(0)
		return 0
	}
	r, _, _ := pDefWindowProc.Call(uintptr(h), uintptr(message), wParam, lParam)
	return r
}

func main() {
	noServer := flag.Bool("no-server", false, "show the tray icon without starting the server (tests)")
	smoke := flag.Bool("smoke", false, "show the icon, then close (tests)")
	iconCheck := flag.Bool("icon-check", false, "exit 0 if the embedded icon loads, 1 if not (tests)")
	flag.Parse()
	if *iconCheck {
		if embeddedIcon() != 0 {
			os.Exit(0)
		}
		os.Exit(1)
	}

	root = installRoot()
	port = webUIPort()

	// One copy only: a second start just opens the browser.
	mutexName := utf16(`Local\AgentZeroWindowsLauncher-` + strconv.FormatUint(uint64(hashPath(root)), 16))
	_, _, errno := pCreateMutex.Call(0, 0, uintptr(unsafe.Pointer(mutexName)))
	if errno == syscall.Errno(errorAlreadyExists) && !*smoke {
		openBrowser("")
		return
	}

	if !*noServer {
		startServer()
	}

	instance, _, _ := pGetModuleHandle.Call(0)
	className := utf16("AgentZeroLauncherTray")
	cls := wndClass{wndProc: syscall.NewCallback(wndProc), instance: syscall.Handle(instance), className: className}
	pRegisterClass.Call(uintptr(unsafe.Pointer(&cls)))
	h, _, _ := pCreateWindowEx.Call(0, uintptr(unsafe.Pointer(className)), uintptr(unsafe.Pointer(utf16(appName))), 0, 0, 0, 0, 0, 0, 0, instance, 0)
	hwnd = syscall.Handle(h)

	nid = notifyIconData{size: uint32(unsafe.Sizeof(notifyIconData{})), hwnd: hwnd, id: 1,
		flags: nifMessage | nifIcon | nifTip, callbackMessage: wmTray, icon: loadIcon()}
	tip := syscall.StringToUTF16(fmt.Sprintf("%s - localhost:%d", appName, port))
	copy(nid.tip[:], tip)
	pNotifyIcon.Call(nimAdd, uintptr(unsafe.Pointer(&nid)))

	if *smoke {
		pPostMessage.Call(uintptr(hwnd), wmClose, 0, 0)
	}

	var m msg
	for {
		r, _, _ := pGetMessage.Call(uintptr(unsafe.Pointer(&m)), 0, 0, 0)
		if int32(r) <= 0 {
			break
		}
		pTranslate.Call(uintptr(unsafe.Pointer(&m)))
		pDispatch.Call(uintptr(unsafe.Pointer(&m)))
	}
}

func hashPath(s string) uint32 {
	var h uint32 = 2166136261
	for _, c := range strings.ToLower(s) {
		h ^= uint32(c)
		h *= 16777619
	}
	return h
}
