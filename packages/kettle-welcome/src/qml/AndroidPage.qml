// SPDX-License-Identifier: BSD-3-Clause
// Android games: add an .apk (or an .xapk/.apks bundle) to Steam set to run with Lepton (Kettle),
// find one on F-Droid, or, opt-in, download one from Google Play with the user's Google account.
// The work is done by kettle-android-games (package kettle-lepton).
import QtCore
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Dialogs
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import org.kettle.welcome

BasePage {
    id: page

    title: "Android"
    heading: "Android games"
    description: "Android games run in Steam through Lepton, the Android layer Valve made for the Steam Frame. Add an APK file, pick a game from F-Droid, or download one from Google Play, and it appears in your Steam library, ready to play in Game Mode with the built-in controls."

    // the last result: {ok, error} or the added game
    property var result: null
    property var searchResults: []
    property var playResults: []
    property string lastCommand: ""
    // the Google account signed in for Google Play downloads ("" when none)
    property string playEmail: ""

    Component.onCompleted: Backend.androidGames("play-status", "")

    Connections {
        target: Backend
        function onAndroidResult(command, res) {
            if (command === "play-status" || command === "play-signout") {
                page.playEmail = res.ok ? res.email : "";
            } else if (command === "play-signin") {
                if (res.ok)
                    page.playEmail = res.email;
                page.result = res.ok ? null : res;
            } else if (command === "fdroid-search") {
                page.searchResults = res.ok ? res.apps : [];
                page.result = res.ok ? null : res;
            } else if (command === "play-search") {
                page.playResults = res.ok ? res.apps : [];
                page.result = res.ok ? null : res;
            } else {
                page.result = res;
            }
        }
    }

    function run(command, arg) {
        page.lastCommand = command;
        page.result = null;
        Backend.androidGames(command, arg);
    }

    FileDialog {
        id: fileDialog
        title: "Add an Android game"
        nameFilters: ["Android games (*.apk *.xapk *.apks)"]
        currentFolder: "file://" + StandardPaths.writableLocation(StandardPaths.DownloadLocation)
        onAccepted: page.run("add", decodeURIComponent(selectedFile.toString().replace(/^file:\/\//, "")))
    }

    TileGrid {
        Tile {
            iconName: "document-open"
            title: "Add an APK file"
            subtitle: "An Android game you downloaded (.apk, .xapk or .apks). It's copied to Games/Android in your home folder."
            enabled: !Backend.androidBusy
            onClicked: fileDialog.open()
        }
        Tile {
            iconName: "steam"
            title: "Steam"
            subtitle: "Added games are in your library. They run with the Lepton (Kettle) compatibility tool, set for you."
            onClicked: Backend.launchApp("steam")
        }
    }

    // what the last command is doing or did; Google Play's under its own section
    Status {
        forPlay: false
    }

    Section {
        title: "Find games on F-Droid"
        description: "F-Droid is a catalogue of free and open-source Android apps. Search it, then add a game straight to Steam."
    }

    RowLayout {
        Layout.fillWidth: true

        Kirigami.SearchField {
            id: searchField
            Layout.fillWidth: true
            placeholderText: "Search F-Droid, e.g. dungeon, chess, racing"
            autoAccept: false
            onAccepted: if (text.trim().length > 0) page.run("fdroid-search", text.trim())
        }
        QQC2.Button {
            text: "Search"
            icon.name: "search"
            enabled: !Backend.androidBusy && searchField.text.trim().length > 0
            onClicked: page.run("fdroid-search", searchField.text.trim())
        }
    }

    ResultList {
        results: page.searchResults
        searchCommand: "fdroid-search"
        addCommand: "fdroid-add"
    }

    Section {
        title: "Google Play (optional)"
        description: "Download games you own on Google Play, or free ones, with your Google account. Google doesn't support this: it uses apkeep, an unofficial downloader, and signing in agrees to Google Play's Terms of Service for it. Google may restrict accounts it finds using unofficial downloaders, so a second Google account is the safer choice. The sign-in is kept only on this device."
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.largeSpacing

        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: page.playEmail ? "Signed in as " + page.playEmail + "." : "Not signed in."
        }
        QQC2.Button {
            visible: !!page.playEmail
            text: "Sign out"
            icon.name: "system-log-out"
            enabled: !Backend.androidBusy
            onClicked: page.run("play-signout", "")
        }
    }

    // Signing in is apkeep's documented way: Google's embedded setup page, in Firefox, sets a
    // one-time oauth_token cookie, which kettle-android-games reads from Firefox's profile and
    // trades for a long-lived token.
    ColumnLayout {
        Layout.fillWidth: true
        visible: !page.playEmail
        spacing: Kirigami.Units.largeSpacing

        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: "1. Open Google's sign-in page in Firefox and sign in. At the end the page may stay blank or keep loading; that's expected."
        }
        QQC2.Button {
            text: "Open Google sign-in"
            icon.name: "internet-web-browser"
            onClicked: Qt.openUrlExternally("https://accounts.google.com/EmbeddedSetup")
        }
        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: "2. Wait a few seconds, come back here and finish. The sign-in is picked up from Firefox. If you're asked for it, enter the account's email address first."
        }
        RowLayout {
            Layout.fillWidth: true

            QQC2.TextField {
                id: emailField
                Layout.fillWidth: true
                placeholderText: "Email address (only if asked)"
                inputMethodHints: Qt.ImhEmailCharactersOnly | Qt.ImhNoAutoUppercase
            }
            QQC2.Button {
                text: "Finish sign-in"
                icon.name: "dialog-ok"
                enabled: !Backend.androidBusy
                onClicked: page.run("play-signin", emailField.text.trim())
            }
        }
    }

    // Games come to this device only through here: the Install button of the Google Play
    // website sends them to the account's Android phones.
    RowLayout {
        Layout.fillWidth: true
        visible: !!page.playEmail

        Kirigami.SearchField {
            id: playSearchField
            Layout.fillWidth: true
            placeholderText: "Search Google Play, or paste a game's Google Play link"
            autoAccept: false
            onAccepted: page.playSearchOrAdd()
        }
        QQC2.Button {
            text: /^(https?:|market:)/.test(playSearchField.text.trim()) ? "Download and add" : "Search"
            icon.name: /^(https?:|market:)/.test(playSearchField.text.trim()) ? "download" : "search"
            enabled: !Backend.androidBusy && playSearchField.text.trim().length > 0
            onClicked: page.playSearchOrAdd()
        }
    }

    Status {
        forPlay: true
    }

    ResultList {
        visible: !!page.playEmail
        results: page.playResults
        searchCommand: "play-search"
        addCommand: "play-add"
        addText: "Download and add"
    }

    function playSearchOrAdd() {
        const text = playSearchField.text.trim();
        if (text.length === 0 || Backend.androidBusy)
            return;
        page.run(/^(https?:|market:)/.test(text) ? "play-add" : "play-search", text);
    }

    component Status: ColumnLayout {
        property bool forPlay

        Layout.fillWidth: true
        spacing: Kirigami.Units.largeSpacing
        visible: page.lastCommand.startsWith("play-") === forPlay

        // download progress, while fdroid-add or play-add downloads
        ColumnLayout {
            Layout.fillWidth: true
            visible: Backend.androidBusy && Backend.androidDownloadTotal > 0
            spacing: Kirigami.Units.smallSpacing

            QQC2.ProgressBar {
                Layout.fillWidth: true
                from: 0
                to: Math.max(Backend.androidDownloadTotal, 1)
                value: Backend.androidDownloaded
            }
            QQC2.Label {
                Layout.fillWidth: true
                opacity: 0.8
                text: {
                    const mb = n => n >= 1e9 ? (n / 1e9).toFixed(2) + " GB" : Math.round(n / 1e6) + " MB";
                    const done = Backend.androidDownloaded >= Backend.androidDownloadTotal;
                    return done ? "Downloaded " + mb(Backend.androidDownloadTotal) + ", adding to Steam…"
                                : mb(Backend.androidDownloaded) + " of " + mb(Backend.androidDownloadTotal)
                                  + " (" + Math.floor(100 * Backend.androidDownloaded / Backend.androidDownloadTotal) + "%)";
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.largeSpacing
            visible: (Backend.androidBusy && page.lastCommand !== "") || page.result !== null

            QQC2.BusyIndicator {
                visible: Backend.androidBusy
                running: visible
                Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                Layout.preferredWidth: Layout.preferredHeight
            }
            QQC2.Label {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                color: page.result && !page.result.ok ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
                text: {
                    if (Backend.androidBusy)
                        return page.lastCommand === "fdroid-search" ? "Searching F-Droid…"
                            : page.lastCommand === "fdroid-add" ? "Downloading from F-Droid and adding to Steam…"
                            : page.lastCommand === "play-signin" ? "Signing in to Google Play…"
                            : page.lastCommand === "play-search" ? "Searching Google Play…"
                            : page.lastCommand === "play-add" ? "Downloading from Google Play and adding to Steam… Big games take a while; you can keep using the device."
                            : page.lastCommand === "play-status" || page.lastCommand === "" ? ""
                            : "Adding to Steam…";
                    const r = page.result;
                    if (!r)
                        return "";
                    if (!r.ok)
                        return r.error;
                    let text = r.name + " is in your Steam library, set to run with Lepton (Kettle).";
                    if (r.google_services)
                        text += " It uses Google Play services, which aren't available here, so it may not start.";
                    return text;
                }
            }
        }
    }

    component ResultList: ColumnLayout {
        id: list

        property var results: []
        property string searchCommand
        property string addCommand
        property string addText: "Add to Steam"

        Layout.fillWidth: true
        spacing: Kirigami.Units.largeSpacing

        QQC2.Label {
            Layout.fillWidth: true
            visible: page.lastCommand === list.searchCommand && !Backend.androidBusy && page.result === null
                     && list.results.length === 0
            text: "Nothing found."
            opacity: 0.8
        }

        Repeater {
            model: list.results

            delegate: RowLayout {
                required property var modelData

                Layout.fillWidth: true
                spacing: Kirigami.Units.largeSpacing

                Image {
                    source: modelData.icon
                    asynchronous: true
                    fillMode: Image.PreserveAspectFit
                    Layout.preferredWidth: Kirigami.Units.iconSizes.large
                    Layout.preferredHeight: Kirigami.Units.iconSizes.large
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0

                    QQC2.Label {
                        Layout.fillWidth: true
                        text: modelData.name
                        font.bold: true
                        elide: Text.ElideRight
                    }
                    QQC2.Label {
                        Layout.fillWidth: true
                        text: modelData.summary
                        wrapMode: Text.Wrap
                        opacity: 0.8
                    }
                }
                QQC2.Button {
                    text: list.addText
                    icon.name: "list-add"
                    enabled: !Backend.androidBusy
                    onClicked: page.run(list.addCommand, modelData.package)
                }
            }
        }
    }

    Section {
        title: "What runs"
        description: "Games built for 64-bit ARM phones running Android 11 or older, which is most of them. Not supported: games that need Google Play services, a Google sign-in or Google Play purchases inside the game, games that download extra data through Google Play after starting, and games made only for x86. Each game keeps its own saves. In the Files app you can also right-click an APK file and choose Add to Steam as Android game."
    }
}
