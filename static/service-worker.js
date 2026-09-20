"use strict";

/*
 * PixelSentinel Service Worker
 *
 * Handles:
 *   - Service Worker installation
 *   - Service Worker activation
 *   - Incoming Web Push notifications
 *
 * Notification click navigation will be expanded later
 * when PixelSentinel's album-link behavior is implemented.
 */

self.addEventListener("install", () => {
    self.skipWaiting();
});

self.addEventListener("activate", event => {
    event.waitUntil(
        self.clients.claim()
    );
});

function sleep(milliseconds) {
    return new Promise(
        resolve => setTimeout(
            resolve,
            milliseconds
        )
    );
}

async function acknowledgeSubscriptionRemoval(
    removalToken
) {
    /*
     * The browser may already be unsubscribed by the
     * time this request is sent, so make a few short
     * attempts before giving up.
     *
     * The raw removal token is never written to storage
     * or logged.
     */

    const retryDelays = [
        0,
        1000,
        2000,
        4000
    ];


    for (
        let attempt = 0;
        attempt < retryDelays.length;
        attempt += 1
    ) {

        if (retryDelays[attempt] > 0) {

            await sleep(
                retryDelays[attempt]
            );
        }


        try {

            const response = await fetch(
                "/api/removal/ack",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    credentials:
                        "same-origin",

                    cache:
                        "no-store",

                    referrerPolicy:
                        "no-referrer",

                    body: JSON.stringify({
                        removal_token:
                            removalToken
                    })
                }
            );


            if (response.ok) {

                return true;
            }


            /*
             * 404 means the removal credential is no
             * longer valid, expired, or was already
             * consumed. Retrying will not help.
             */

            if (response.status === 404) {

                return false;
            }


            /*
             * 400 / 403 indicate a request that the
             * server deliberately rejected.
             */

            if (
                response.status === 400
                || response.status === 403
            ) {

                return false;
            }

        } catch {

            /*
             * A short retry may recover from a
             * temporary network interruption.
             */
        }
    }


    return false;
}

async function handleSubscriptionRemoval(
    payload
) {
    /*
     * Process a server-authorized request to remove this
     * browser's PixelSentinel push subscription.
     */

    const removalToken =
        typeof payload.removal_token === "string"
            ? payload.removal_token.trim()
            : "";

    if (
        !removalToken
        || removalToken.length > 256
    ) {

        /*
         * Invalid removal payload.
         *
         * Because this was still delivered as a Web
         * Push event, show a user-visible notification
         * rather than silently consuming the push.
         */

        await self.registration.showNotification(
            "PixelSentinel Alerts",
            {
                body:
                    "PixelSentinel could not process "
                    + "a notification settings change.",

                icon:
                    "/static/icons/icon-192.png",

                badge:
                    "/static/icons/icon-192.png",

                tag:
                    "pixelsentinel-removal-error"
            }
        );

        return;
    }

    /*
     * Web Push should remain user-visible.
     * Show this before unregistering the subscription.
     */

    await self.registration.showNotification(
        "PixelSentinel Alerts",
        {
            body:
                "Photo alerts have been removed "
                + "from this device.",

            icon:
                "/static/icons/icon-192.png",

            badge:
                "/static/icons/icon-192.png",

            tag:
                "pixelsentinel-subscription-removed",

            renotify:
                false,

            data: {
                type:
                    "subscription_removed"
            }
        }
    );

    let subscription = null;

    try {

        subscription =
            await self.registration.pushManager
                .getSubscription();

    } catch {

        /*
         * Do not acknowledge server-side deletion if we
         * cannot determine the browser subscription
         * state.
         */

        return;
    }

    /*
     * If the browser reports no existing subscription,
     * it is already unsubscribed from the remote push
     * service. We can safely acknowledge the removal.
     */

    if (subscription === null) {

        await acknowledgeSubscriptionRemoval(
            removalToken
        );

        return;
    }

    let unsubscribed = false;

    try {

        unsubscribed =
            await subscription.unsubscribe();

    } catch {

        /*
         * Leave the server subscription intact so the
         * removal remains pending rather than falsely
         * claiming success.
         */

        return;
    }

    if (!unsubscribed) {

        return;
    }

    /*
     * Apple / Google / Mozilla browser subscription is removed.
     * PixelSentinel can delete its
     * corresponding local database record.
     */

    await acknowledgeSubscriptionRemoval(
        removalToken
    );
}

self.addEventListener(
    "push",
    event => {

        let payload = {};

        try {

            if (event.data) {

                payload =
                    event.data.json();
            }

        } catch {

            payload = {};
        }

        /*
         * Remote device-removal command.
         */

        if (
            payload
            && payload.type ===
                "subscription_removal"
        ) {

            event.waitUntil(
                handleSubscriptionRemoval(
                    payload
                )
            );

            return;
        }

        /*
         * Normal PixelSentinel notification.
         */

        const title =
            typeof payload.title === "string"
                ? payload.title.slice(
                    0,
                    100
                )
                : "PixelSentinel Alerts";

        const body =
            typeof payload.body === "string"
                ? payload.body.slice(
                    0,
                    300
                )
                : "New photos are available.";

        const notificationType =
            typeof payload.type === "string"
                ? payload.type.slice(
                    0,
                    50
                )
                : "photo_alert";

        event.waitUntil(
            self.registration.showNotification(
                title,
                {
                    body:
                        body,

                    icon:
                        "/static/icons/icon-192.png",

                    badge:
                        "/static/icons/icon-192.png",

                    data: {
                        type:
                            notificationType
                    }
                }
            )
        );
    }
);

self.addEventListener(
    "notificationclick",
    event => {

        /*
         * For Phase 4, clicking a notification simply
         * dismisses it.
         *
         * We deliberately do NOT call openWindow() on a
         * URL supplied in the push payload yet.
         *
         * Album navigation will be added later with
         * destination validation.
         */

        event.notification.close();
    }
);
