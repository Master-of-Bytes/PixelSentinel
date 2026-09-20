"use strict";


let deferredInstallPrompt = null;
let vapidPublicKey = null;
let pushServiceWorkerRegistration = null;

const pushEnrollment =
    document.getElementById("push-enrollment");

const pushStatus =
    document.getElementById("push-status");

const enablePushButton =
    document.getElementById("enable-push-button");


const inviteUsed =
    pushEnrollment?.dataset.inviteUsed === "true";


/*
 * Detect the operating-system family.
 *
 * This is used only to customize instructions.
 * Actual Web Push compatibility is determined
 * separately through feature detection.
 */
function detectPlatform() {

    const ua = navigator.userAgent || "";

    const reportedPlatform =
        navigator.userAgentData?.platform ||
        navigator.platform ||
        "";

    /*
     * Modern iPads can sometimes identify
     * themselves as Macintosh devices.
     */
    const ipadAsMac =
        reportedPlatform === "MacIntel" &&
        navigator.maxTouchPoints > 1;

    if (
        /iPhone|iPad|iPod/i.test(ua) ||
        ipadAsMac
    ) {
        return "ios";
    }

    if (/Android/i.test(ua)) {
        return "android";
    }

    return "other";
}


/*
 * Detect whether the PWA is currently running
 * from the Home Screen / installed app mode.
 */
function isStandalone() {

    const displayModeStandalone =
        window.matchMedia(
            "(display-mode: standalone)"
        ).matches;

    const iosStandalone =
        window.navigator.standalone === true;

    return (
        displayModeStandalone ||
        iosStandalone
    );
}


/*
 * Try to determine the major iOS version
 * only so we can display the iOS 26
 * "Open as Web App" instruction.
 */
function getIOSMajorVersion() {

    const match =
        navigator.userAgent.match(
            /OS (\d+)[._]/i
        );

    if (!match) {
        return null;
    }

    return parseInt(match[1], 10);
}


/*
 * Capability detection.
 *
 * These checks matter more than the
 * device-name detection above.
 */
function getCapabilities() {

    return {
        secureContext:
            window.isSecureContext,

        serviceWorker:
            "serviceWorker" in navigator,

        notifications:
            "Notification" in window,

        pushManager:
            "PushManager" in window
    };
}


function showElement(id) {

    const element =
        document.getElementById(id);

    if (element) {
        element.classList.remove("hidden");
    }
}


function hideElement(id) {

    const element =
        document.getElementById(id);

    if (element) {
        element.classList.add("hidden");
    }
}


function renderCapabilities(capabilities) {

    const container =
        document.getElementById(
            "capability-list"
        );

    container.innerHTML = "";

    const checks = [
        [
            "Secure connection",
            capabilities.secureContext
        ],
        [
            "Service Worker",
            capabilities.serviceWorker
        ],
        [
            "Notifications API",
            capabilities.notifications
        ],
        [
            "Push API",
            capabilities.pushManager
        ]
    ];

    for (const [label, result] of checks) {

        const row =
            document.createElement("div");

        row.className =
            result
                ? "capability capability-ok"
                : "capability capability-bad";

        row.textContent = label;

        container.appendChild(row);
    }
}


function renderIOS() {

    showElement("ios-setup");

    const standalone =
        isStandalone();

    if (standalone) {

        hideElement(
            "ios-install-required"
        );

        showElement(
            "ios-installed"
        );

    } else {

        showElement(
            "ios-install-required"
        );

        hideElement(
            "ios-installed"
        );

        const majorVersion =
            getIOSMajorVersion();

        if (
            majorVersion !== null &&
            majorVersion >= 26
        ) {
            showElement("ios26-step");
        }
    }
}


function renderAndroid() {

    showElement("android-setup");
}


function renderOther() {

    showElement("other-setup");
}


async function registerServiceWorker() {

    if (
        !window.isSecureContext ||
        !("serviceWorker" in navigator)
    ) {
        return;
    }

    try {

        const registration =
            await navigator.serviceWorker.register(
                "/service-worker.js",
                {
                    scope: "/"
                }
            );

        console.log(
            "PixelSentinel service worker registered:",
            registration.scope
        );

    } catch (error) {

        console.error(
            "Service worker registration failed:",
            error
        );
    }
}


async function loadVapidPublicKey() {

    /*
     * Build the API path from the current private
     * enrollment URL.
     *
     * Example:
     *
     * /enroll/<token>
     *
     * becomes:
     *
     * /enroll/<token>/api/vapid-public-key
     */

    const enrollmentPath =
        window.location.pathname.replace(
            /\/$/,
            ""
        );

    const url =
        `${enrollmentPath}/api/vapid-public-key`;

    try {

        const response = await fetch(
            url,
            {
                method: "GET",

                headers: {
                    "Accept": "application/json"
                },

                credentials: "same-origin",

                cache: "no-store"
            }
        );

        if (!response.ok) {
            return null;
        }

        const data =
            await response.json();

        if (
            !data
            || data.ok !== true
            || typeof data.public_key !== "string"
            || !data.public_key.trim()
        ) {
            return null;
        }

        return data.public_key.trim();

    } catch {
        return null;
    }
}


async function preparePushEnrollment() {

    if (!enablePushButton) {
        return;
    }


    /*
     * A used invite must never enable registration.
     */

    if (inviteUsed) {

        enablePushButton.disabled = true;

        return;
    }


    /*
     * Web Push requires a secure context.
     */

    if (!window.isSecureContext) {

        enablePushButton.disabled = true;

        setPushStatus(
            "A secure connection is required to enable photo alerts.",
            "error"
        );

        return;
    }


    /*
     * Required browser APIs.
     */

    if (
        !("serviceWorker" in navigator)
        || !("Notification" in window)
        || !("PushManager" in window)
    ) {

        enablePushButton.disabled = true;

        setPushStatus(
            "This browser does not support PixelSentinel notifications.",
            "error"
        );

        return;
    }


    /*
     * iPhone/iPad Web Push must run from the installed
     * Home Screen web app.
     */

    const platform =
        detectPlatform();

    if (
        platform === "ios"
        && !isStandalone()
    ) {

        enablePushButton.disabled = true;

        setPushStatus(
            "Add PixelSentinel to your Home Screen, then open it from the Home Screen to continue.",
            "info"
        );

        return;
    }


    /*
     * If notification permission was previously denied,
     * JavaScript cannot simply ask again.
     */

    if (
        Notification.permission === "denied"
    ) {

        enablePushButton.disabled = true;

        setPushStatus(
            "Notifications are blocked for PixelSentinel. Enable notifications in your device or browser settings to continue.",
            "error"
        );

        return;
    }


    /*
     * Wait for the active PixelSentinel Service Worker.
     */

    try {

        pushServiceWorkerRegistration =
            await navigator.serviceWorker.ready;

    } catch {

        enablePushButton.disabled = true;

        setPushStatus(
            "PixelSentinel could not prepare notification services.",
            "error"
        );

        return;
    }


    /*
     * Fetch the server's public VAPID application key.
     */

    vapidPublicKey =
        await loadVapidPublicKey();

    if (!vapidPublicKey) {

        enablePushButton.disabled = true;

        setPushStatus(
            "PixelSentinel notification setup is temporarily unavailable.",
            "error"
        );

        return;
    }


    /*
     * All prerequisites are satisfied.
     */

    enablePushButton.disabled = false;
}


function setPushStatus(
    message,
    type = "info"
) {

    if (!pushStatus) {
        return;
    }

    pushStatus.textContent =
        message;

    pushStatus.classList.remove(
        "status-info",
        "status-success",
        "status-error"
    );

    pushStatus.classList.add(
        `status-${type}`
    );
}


if (inviteUsed) {

    setPushStatus(
        "This device cannot be registered again with this enrollment link.",
        "info"
    );

    if (enablePushButton) {
        enablePushButton.disabled = true;
    }
}


/*
 * Android / Chromium may provide an
 * installation prompt.
 *
 * Installation is optional on Android.
 */
window.addEventListener(
    "beforeinstallprompt",
    event => {

        event.preventDefault();

        deferredInstallPrompt =
            event;

        showElement(
            "android-install"
        );
    }
);


document
    .getElementById("android-install")
    ?.addEventListener(
        "click",
        async () => {

            if (!deferredInstallPrompt) {
                return;
            }

            deferredInstallPrompt.prompt();

            await deferredInstallPrompt
                .userChoice;

            deferredInstallPrompt = null;

            hideElement(
                "android-install"
            );
        }
    );


function urlBase64ToUint8Array(
    base64String
) {

    /*
     * Convert the Base64URL VAPID public key into the
     * Uint8Array required by PushManager.subscribe().
     */

    if (
        typeof base64String !== "string"
        || !base64String.trim()
    ) {
        throw new Error(
            "Invalid application server key."
        );
    }

    const padding =
        "=".repeat(
            (
                4
                - base64String.length % 4
            ) % 4
        );

    const base64 =
        (
            base64String
            + padding
        )
            .replace(/-/g, "+")
            .replace(/_/g, "/");

    const rawData =
        window.atob(
            base64
        );

    const outputArray =
        new Uint8Array(
            rawData.length
        );

    for (
        let index = 0;
        index < rawData.length;
        index += 1
    ) {

        outputArray[index] =
            rawData.charCodeAt(
                index
            );
    }

    /*
     * A VAPID P-256 application-server public key
     * should decode to a 65-byte uncompressed EC point.
     */

    if (
        outputArray.length !== 65
    ) {
        throw new Error(
            "Invalid application server key."
        );
    }

    return outputArray;
}


async function initializeSetup() {

    const platform =
        detectPlatform();

    const capabilities =
        getCapabilities();

    const status =
        document.getElementById(
            "device-status"
        );

    if (
        !capabilities.secureContext
    ) {

        showElement(
            "secure-warning"
        );
    }

    switch (platform) {

        case "ios":

            renderIOS();

            break;


        case "android":

            renderAndroid();

            break;


        default:

            renderOther();

            break;
    }

    renderCapabilities(
        capabilities
    );

    await registerServiceWorker();

    await preparePushEnrollment();
}


/*
 * Detect Brave without relying on the User-Agent string.
 *
 * Brave exposes navigator.brave.isBrave() on supported
 * desktop and Android versions.
 *
 * Client Hints are used only as a fallback.
 */
async function isBraveBrowser() {

    try {

        if (
            navigator.brave
            && typeof navigator.brave.isBrave === "function"
        ) {

            return await navigator.brave.isBrave();
        }

    } catch {
        // Continue to fallback detection.
    }

    return Boolean(
        navigator.userAgentData?.brands?.some(
            brand =>
                brand.brand === "Brave"
        )
    );
}


async function createPushSubscription() {

    if (
        !enablePushButton
        || inviteUsed
    ) {
        return null;
    }

    if (
        !pushServiceWorkerRegistration
        || !vapidPublicKey
    ) {

        setPushStatus(
            "PixelSentinel notification setup is temporarily unavailable.",
            "error"
        );

        return null;
    }

    enablePushButton.disabled =
        true;


    /*
     * Notification permission must be requested as a
     * direct result of the user's button click.
     */

    let permission;

    try {

        permission =
            await Notification.requestPermission();

    } catch {

        setPushStatus(
            "Notification permission could not be requested.",
            "error"
        );

        enablePushButton.disabled =
            false;

        return null;
    }


    if (
        permission !== "granted"
    ) {

        if (
            permission === "denied"
        ) {

            setPushStatus(
                "Notifications are blocked for PixelSentinel. Enable notifications in your device or browser settings to continue.",
                "error"
            );

        } else {

            setPushStatus(
                "Notification permission is required to enable photo alerts.",
                "info"
            );

            enablePushButton.disabled =
                false;
        }

        return null;
    }


    try {

        /*
         * Reuse an existing subscription if this
         * Service Worker already has one.
         */

        let subscription =
            await pushServiceWorkerRegistration
                .pushManager
                .getSubscription();

        if (!subscription) {

            const applicationServerKey =
                urlBase64ToUint8Array(
                    vapidPublicKey
                );

            subscription =
                await pushServiceWorkerRegistration
                    .pushManager
                    .subscribe({
                        userVisibleOnly: true,
                        applicationServerKey:
                            applicationServerKey
                    });
        }

        return subscription;

    } catch (error) {

        /*
         * Brave can expose the standard Web Push APIs
         * even when its Google push-messaging service
         * is disabled.
         *
         * In that situation subscribe() commonly fails
         * with AbortError.
         */

        const braveBrowser =
            await isBraveBrowser();

        if (
            braveBrowser
            && error?.name === "AbortError"
        ) {

            setPushStatus(
                "Brave could not connect to its push service. In Brave Settings, search for \"push messaging\" and enable \"Use Google services for push messaging,\" then restart Brave and try again.",
                "error"
            );

        } else {

            setPushStatus(
                "PixelSentinel could not enable notifications on this device.",
                "error"
            );
        }

        enablePushButton.disabled =
            false;

        return null;
    }
}

async function registerPushSubscription(
    subscription
) {
    if (
        !subscription
        || typeof subscription.toJSON !== "function"
    ) {
        return false;
    }


    const subscriptionData =
        subscription.toJSON();

    if (
        !subscriptionData
        || typeof subscriptionData.endpoint !== "string"
        || !subscriptionData.endpoint
        || !subscriptionData.keys
        || typeof subscriptionData.keys.p256dh !== "string"
        || !subscriptionData.keys.p256dh
        || typeof subscriptionData.keys.auth !== "string"
        || !subscriptionData.keys.auth
    ) {
        return false;
    }

    const enrollmentPath =
        window.location.pathname.replace(
            /\/$/,
            ""
        );

    const url =
        `${enrollmentPath}/api/subscribe`;


    try {

        const response =
            await fetch(
                url,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json",

                        "Accept":
                            "application/json"
                    },

                    credentials:
                        "same-origin",

                    cache:
                        "no-store",

                    referrerPolicy:
                        "no-referrer",

                    body:
                        JSON.stringify({
                            platform:
                                detectPlatform(),

                            subscription:
                                subscriptionData
                        })
                }
            );


        /*
         * An invalid/expired/used invitation should
         * not be repeatedly retried from this page.
         */

        if (response.status === 403) {

            enablePushButton.disabled =
                true;

            setPushStatus(
                "This enrollment link can no longer be used.",
                "error"
            );

            return false;
        }


        let result = null;

        try {

            result =
                await response.json();

        } catch {

            result = null;
        }


        if (
            !response.ok
            || !result
            || result.ok !== true
        ) {

            setPushStatus(
                "PixelSentinel could not complete notification registration. Please try again.",
                "error"
            );

            enablePushButton.disabled =
                false;

            return false;
        }


        return true;

    } catch {

        setPushStatus(
            "PixelSentinel could not contact the notification service. Please try again.",
            "error"
        );

        enablePushButton.disabled =
            false;

        return false;
    }
}

enablePushButton?.addEventListener(
    "click",
    async () => {

        enablePushButton.disabled =
            true;


        /*
         * Step 1:
         * Obtain or reuse the browser's
         * PushSubscription.
         */

        const subscription =
            await createPushSubscription();

        if (!subscription) {
            return;
        }


        /*
         * Step 2:
         * Send it to PixelSentinel.
         */

        const registered =
            await registerPushSubscription(
                subscription
            );

        if (!registered) {
            return;
        }


        /*
         * Full PixelSentinel registration succeeded.
         */

        enablePushButton.textContent =
            "Photo Alerts Registered";

        enablePushButton.disabled =
            true;

        setPushStatus(
            "Photo alerts are enabled.",
            "success"
        );
    }
);


document.addEventListener(
    "DOMContentLoaded",
    initializeSetup
);