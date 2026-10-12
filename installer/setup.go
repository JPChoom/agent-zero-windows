//go:build windows

// Agent Zero for Windows setup: a single .exe around install.ps1.
//
// It embeds install.ps1, writes it to a temporary folder, runs it with
// Windows PowerShell (passing the options below through) and removes it
// again. All the work - checks, download, environment, Start menu and Apps
// entries, the optional llama.cpp server - is done by install.ps1, so the
// .exe and the script never disagree. Standard library only.
//
// Build: installer\build.ps1 (go build; no other tools needed).
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
	"syscall"
	"unsafe"
)

//go:embed install.ps1
var installScript []byte

const appName = "Agent Zero for Windows"

func main() {
	version := flag.String("version", "", "release tag to install, e.g. v1.4 (default: the latest release)")
	dir := flag.String("dir", "", `install folder (default: %LOCALAPPDATA%\Programs\AgentZeroWindows)`)
	llama := flag.String("llama", "ask", "llama.cpp server build to download: ask, auto, cuda, vulkan, rocm, cpu or none")
	noShortcut := flag.Bool("no-shortcut", false, "do not add a Start menu entry (or a desktop shortcut)")
	desktop := flag.String("desktop", "ask", "desktop shortcut: ask, yes or no")
	force := flag.Bool("force", false, "skip the Windows 11 check")
	flag.Parse()

	fmt.Printf("%s setup\n\n", appName)
	code := run(*version, *dir, *llama, *desktop, *noShortcut, *force)
	if startedByDoubleClick() {
		fmt.Print("\nPress Enter to close this window...")
		_, _ = bufio.NewReader(os.Stdin).ReadString('\n')
	}
	os.Exit(code)
}

func run(version, dir, llama, desktop string, noShortcut, force bool) int {
	tmp, err := os.MkdirTemp("", "a0w-setup-")
	if err != nil {
		fmt.Println("ERROR: cannot create a temporary folder:", err)
		return 1
	}
	defer os.RemoveAll(tmp)

	script := filepath.Join(tmp, "install.ps1")
	// A UTF-8 byte order mark so Windows PowerShell 5.1 never misreads the file.
	if err := os.WriteFile(script, append([]byte{0xEF, 0xBB, 0xBF}, installScript...), 0o600); err != nil {
		fmt.Println("ERROR: cannot write the installer script:", err)
		return 1
	}

	args := []string{"-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-Llama", llama, "-DesktopShortcut", desktop}
	if version != "" {
		args = append(args, "-Version", version)
	}
	if dir != "" {
		args = append(args, "-InstallDir", dir)
	}
	if noShortcut {
		args = append(args, "-NoShortcut")
	}
	if force {
		args = append(args, "-Force")
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

// startedByDoubleClick reports whether this console belongs to us alone
// (Explorer opened it for the .exe), so the window would close before the
// result can be read. From an existing terminal it returns false.
func startedByDoubleClick() bool {
	proc := syscall.NewLazyDLL("kernel32.dll").NewProc("GetConsoleProcessList")
	if proc.Find() != nil {
		return false
	}
	var pids [4]uint32
	n, _, _ := proc.Call(uintptr(unsafe.Pointer(&pids[0])), uintptr(len(pids)))
	return n == 1
}
