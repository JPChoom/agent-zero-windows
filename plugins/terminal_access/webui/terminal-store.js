import { createStore } from "/js/AlpineStore.js";

export const store = createStore("terminalAccessStore", {
    command: "",
    shell: "powershell",
    output: "",
    status: "idle",
    
    init() {
        // Initialize the store
    },
    
    onOpen() {
        // Called when the modal is opened
        console.log("Terminal Access modal opened");
    },
    
    cleanup() {
        // Called when the modal is closed
        console.log("Terminal Access modal closed");
    },
    
    async executeCommand() {
        if (!this.command.trim()) {
            return;
        }
        
        this.status = "executing";
        this.output = "Executing command...";
        
        try {
            // This would normally call an API endpoint
            // For now, we'll simulate the execution
            const response = await fetch(`/plugins/terminal_access/api/execute`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    command: this.command,
                    shell: this.shell
                })
            });
            
            const result = await response.json();
            
            if (result.status === "success") {
                this.output = result.output;
            } else {
                this.output = `Error: ${result.error}`;
            }
        } catch (error) {
            this.output = `Error: ${error.message}`;
        } finally {
            this.status = "idle";
        }
    }
});
