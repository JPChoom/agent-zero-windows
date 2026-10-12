//go:build windows

// Uninstall.exe - removes an installed Agent Zero for Windows.
//
// It embeds uninstall.ps1 and does the asking itself:
//   - keeps your data (the usr\ folder: chats, memory, settings, secrets,
//     models) unless you also choose to delete it,
//   - removes the program, its Start menu and desktop shortcuts and its
//     Settings > Apps entry.
//
// A program cannot delete the folder it runs from, so on first start it
// copies itself to a temporary folder and continues from there, then removes
// that copy. Standard library only.
package main

import (
	"bufio"
	_ "embed"
	"errors"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

//go:embed assets/uninstall.ps1
var uninstallScript []byte

const appName = "Agent Zero for Windows"

// One reader for every prompt: a second reader would lose input the first had already buffered.
var input = bufio.NewReader(os.Stdin)

// isCopy is true in the temporary copy; every way out of the copy removes it.
var isCopy bool

func main() {
	dir := flag.String("dir", "", "install folder (default: the folder this program is in)")
	yes := flag.Bool("yes", false, "do not ask; keep the data unless -clean is given")
	clean := flag.Bool("clean", false, "also delete the data (usr folder)")
	fromTemp := flag.Bool("from-temp", false, "internal: running from the temporary copy")
	flag.Parse()

	install := *dir
	if install == "" {
		exe, err := os.Executable()
		if err != nil {
			fail("cannot find this program's folder: " + err.Error())
		}
		install = filepath.Dir(exe)
	}

	if !*fromTemp {
		relaunchFromTemp(install, *yes, *clean)
		return
	}
	isCopy = true

	fmt.Printf("%s uninstaller\n\n", appName)
	if _, err := os.Stat(filepath.Join(install, "run_ui.py")); err != nil {
		fail(install + " is not an Agent Zero for Windows folder.")
	}

	deleteData := *clean
	if !*yes {
		fmt.Printf("This removes %s from\n  %s\n\n", appName, install)
		if !confirm("Continue? [y/N] ", false) {
			fmt.Println("Nothing was changed.")
			pauseIfOwnWindow()
			removeSelfLater("")
			return
		}
		if !*clean {
			fmt.Printf("\nYour data (chats, memory, settings, secrets) lives in\n  %s\n", filepath.Join(install, "usr"))
			deleteData = confirm("Delete it as well? Say no to keep it. [y/N] ", false)
		}
	}

	code := runScript(install, deleteData)
	if code == 0 {
		fmt.Println("\nDone.")
	}
	pauseIfOwnWindow()
	removeSelfLater(install)
	os.Exit(code)
}

// relaunchFromTemp copies this program to %TEMP% and starts the copy.
func relaunchFromTemp(install string, yes, clean bool) {
	exe, err := os.Executable()
	if err != nil {
		fail("cannot find this program: " + err.Error())
	}
	data, err := os.ReadFile(exe)
	if err != nil {
		fail("cannot read this program: " + err.Error())
	}
	tmp, err := os.MkdirTemp("", "a0w-uninstall-")
	if err != nil {
		fail("cannot create a temporary folder: " + err.Error())
	}
	copyPath := filepath.Join(tmp, "Uninstall.exe")
	if err := os.WriteFile(copyPath, data, 0o700); err != nil {
		fail("cannot copy this program: " + err.Error())
	}
	args := []string{"-from-temp", "-dir", install}
	if yes {
		args = append(args, "-yes")
	}
	if clean {
		args = append(args, "-clean")
	}
	cmd := exec.Command(copyPath, args...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	// The copy shares this console; wait for it so the window stays until it is done.
	if err := cmd.Run(); err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			os.Exit(exitErr.ExitCode())
		}
		fail("could not start the uninstaller: " + err.Error())
	}
}

func runScript(install string, deleteData bool) int {
	tmp, err := os.MkdirTemp("", "a0w-uninstall-script-")
	if err != nil {
		fmt.Println("ERROR: cannot create a temporary folder:", err)
		return 1
	}
	defer os.RemoveAll(tmp)
	script := filepath.Join(tmp, "uninstall.ps1")
	if err := os.WriteFile(script, append([]byte{0xEF, 0xBB, 0xBF}, uninstallScript...), 0o600); err != nil {
		fmt.Println("ERROR: cannot write the uninstall script:", err)
		return 1
	}
	args := []string{"-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-InstallDir", install, "-Yes"}
	if deleteData {
		args = append(args, "-Clean")
	}
	cmd := exec.Command("powershell.exe", args...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			return exitErr.ExitCode()
		}
		fmt.Println("ERROR: could not start Windows PowerShell:", err)
		return 1
	}
	return 0
}

func confirm(prompt string, def bool) bool {
	fmt.Print(prompt)
	line, _ := input.ReadString('\n')
	switch strings.ToLower(strings.TrimSpace(line)) {
	case "y", "yes":
		return true
	case "n", "no":
		return false
	}
	return def
}

func fail(message string) {
	fmt.Println("ERROR:", message)
	pauseIfOwnWindow()
	if isCopy {
		removeSelfLater("")
	}
	os.Exit(1)
}

// pauseIfOwnWindow waits for Enter when Windows opened this console just for
// us (started from Settings > Apps), so the result can be read.
func pauseIfOwnWindow() {
	proc := syscall.NewLazyDLL("kernel32.dll").NewProc("GetConsoleProcessList")
	if proc.Find() != nil {
		return
	}
	var pids [8]uint32
	n, _, _ := proc.Call(uintptr(unsafe.Pointer(&pids[0])), uintptr(len(pids)))
	if n <= 2 { // this copy and (at most) the launcher that started it
		fmt.Print("\nPress Enter to close this window...")
		_, _ = input.ReadString('\n')
	}
}

// removeSelfLater, once this process and the original Uninstall.exe (still
// waiting for us in the install folder) have exited, deletes the temporary copy
// and - when the program was removed (install != "") - the original and, if
// nothing else is left because the data was deleted too, the install folder.
func removeSelfLater(install string) {
	exe, err := os.Executable()
	if err != nil {
		return
	}
	script := fmt.Sprintf(`ping -n 3 127.0.0.1 >nul & rmdir /s /q "%s"`, filepath.Dir(exe))
	if install != "" {
		script = fmt.Sprintf(`ping -n 3 127.0.0.1 >nul & del /f /q "%s" & rmdir "%s" & rmdir /s /q "%s"`,
			filepath.Join(install, "Uninstall.exe"), install, filepath.Dir(exe))
	}
	// Raw command line: Go would escape the quotes inside `script` in a way
	// cmd.exe does not understand (/s makes it strip just the outer pair).
	cmd := exec.Command("cmd.exe")
	cmd.Dir = os.TempDir() // not inside the folder it is about to remove
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: 0x08000000,
		CmdLine:       `cmd.exe /d /s /c "` + script + `"`,
	}
	_ = cmd.Start()
}
