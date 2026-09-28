// SPDX-License-Identifier: BSD-3-Clause
// Android games: add an .apk (or a single-APK .xapk) to Steam set to run with Lepton (Kettle),
// or find one on F-Droid. The work is done by kettle-android-games (package kettle-lepton).
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
    description: "Android games run in Steam through Lepton, the Android layer Valve made for the Steam Frame. Add an APK file or pick a game from F-Droid, and it appears in your Steam library, ready to play in Game Mode with the built-in controls."

    // the last result: {ok, error} or the added game
    property var result: null
    property var searchResults: []
    property string lastCommand: ""

    Connections {
        target: Backend
        function onAndroidResult(command, res) {
            if (command === "fdroid-search") {
                page.searchResults = res.ok ? res.apps : [];
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
        nameFilters: ["Android games (*.apk *.xapk)"]
        currentFolder: "file://" + StandardPaths.writableLocation(StandardPaths.DownloadLocation)
        onAccepted: page.run("add", decodeURIComponent(selectedFile.toString().replace(/^file:\/\//, "")))
    }

    TileGrid {
        Tile {
            iconName: "document-open"
            title: "Add an APK file"
            subtitle: "An Android game you downloaded (.apk, or an .xapk with one APK). It's copied to Games/Android in your home folder."
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

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.largeSpacing
        visible: Backend.androidBusy || page.result !== null

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

    QQC2.Label {
        Layout.fillWidth: true
        visible: page.lastCommand === "fdroid-search" && !Backend.androidBusy && page.result === null
                 && page.searchResults.length === 0
        text: "Nothing found."
        opacity: 0.8
    }

    Repeater {
        model: page.searchResults

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
                text: "Add to Steam"
                icon.name: "list-add"
                enabled: !Backend.androidBusy
                onClicked: page.run("fdroid-add", modelData.package)
            }
        }
    }

    Section {
        title: "What runs"
        description: "Games built for 64-bit ARM phones, which is most of them. Not supported: games that need Google Play services or a Google sign-in, games split into several APK files (app bundles), and games made only for x86. Each game keeps its own saves. In the Files app you can also right-click an APK file and choose Add to Steam as Android game."
    }
}
