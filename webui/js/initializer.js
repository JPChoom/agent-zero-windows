

import * as device from "./device.js";

export async function initialize(){
    // set device class to body tag
    setDeviceClass();
    // "#settings" in the address opens Settings (the tray launcher's Settings item uses it)
    window.addEventListener("hashchange", openModalFromHash);
    document.addEventListener("alpine:initialized", () => setTimeout(openModalFromHash, 300));
}

const HASH_MODALS = { "#settings": "settings/settings.html" };

function openModalFromHash(){
    const path = HASH_MODALS[window.location.hash];
    if (!path || typeof window.openModal !== "function") return;
    history.replaceState(null, "", window.location.pathname + window.location.search);
    window.openModal(path);
}

function setDeviceClass(){
    device.determineInputType().then((type) => {
        // Remove any class starting with 'device-' from <body>
        const body = document.body;
        body.classList.forEach(cls => {
            if (cls.startsWith('device-')) {
                body.classList.remove(cls);
            }
        });
        // Add the new device class
        body.classList.add(`device-${type}`);
    });
}
