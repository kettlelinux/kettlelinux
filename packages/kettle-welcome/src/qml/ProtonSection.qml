// SPDX-License-Identifier: BSD-3-Clause
// Gaming Extras: community Proton builds with ARM64 releases, installed by welcome-proton into
// Steam's compatibilitytools.d for this user, from the project's own GitHub releases. Like the
// Flatpak installs, they run outside this window, so closing it is fine.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.kirigamiaddons.formcard as FormCard

import org.kettle.welcome

ColumnLayout {
    id: section

    property real maximumWidth

    readonly property var tools: [
        { id: "ge", name: "GE-Proton",
          description: "GloriousEggroll's Proton: Valve's Proton with extra fixes for individual games, a newer Wine, and codecs for games' video scenes." },
        { id: "cachyos", name: "Proton-CachyOS",
          description: "The CachyOS team's Proton: Valve's Proton with a newer Wine, performance patches and extra game fixes." }
    ]
    readonly property var statusWords: Backend.protonStatus.split(" ")
    readonly property bool busy: statusWords[0] === "running"

    function toolName(id) {
        const t = tools.find(t => t.id === id);
        return t ? t.name : id;
    }
    function builds(id) {
        return Backend.protonInstalled.filter(b => b.split(" ")[0] === id).map(b => b.split(" ")[1]);
    }
    function gb(n) {
        return n >= 1e9 ? (n / 1e9).toFixed(2) + " GB" : Math.round(n / 1e6) + " MB";
    }

    Layout.fillWidth: true
    spacing: 0

    Component.onCompleted: Backend.refreshProton()

    FormCard.FormHeader {
        title: "Proton versions for Steam"
        maximumWidth: section.maximumWidth
    }

    QQC2.Label {
        Layout.fillWidth: true
        Layout.maximumWidth: section.maximumWidth
        Layout.alignment: Qt.AlignHCenter
        Layout.bottomMargin: Kirigami.Units.largeSpacing
        wrapMode: Text.Wrap
        opacity: 0.8
        text: "Other builds of Proton, the layer Steam runs Windows games with, from the projects' own ARM64 releases. Steam uses its own Proton unless you choose one of these for a game, in its Properties > Compatibility, or in Game Settings in Game Mode. Each one needs about 2 GB of space."
    }

    FormCard.FormCard {
        maximumWidth: section.maximumWidth

        Repeater {
            model: section.tools

            delegate: FormCard.FormTextDelegate {
                id: toolRow

                required property var modelData
                readonly property var installed: section.builds(modelData.id)
                // folder name of the newest release; undefined until looked up, "-" if that failed
                readonly property var latest: Backend.protonLatest[modelData.id]
                readonly property bool upToDate: latest !== undefined && installed.includes(latest)

                text: modelData.name
                description: modelData.description
                    + (latest !== undefined && latest !== "-" ? "\nNewest: " + latest : "")
                trailing: QQC2.Button {
                    icon.name: toolRow.upToDate ? "checkmark" : "download"
                    text: toolRow.upToDate ? "Up to date" : toolRow.installed.length > 0 ? "Update" : "Install"
                    enabled: !toolRow.upToDate && !section.busy
                    onClicked: Backend.installProton(toolRow.modelData.id)
                }
            }
        }
    }

    // what welcome-proton is doing, or what it last did
    ColumnLayout {
        Layout.fillWidth: true
        Layout.maximumWidth: section.maximumWidth
        Layout.alignment: Qt.AlignHCenter
        Layout.topMargin: Kirigami.Units.largeSpacing
        visible: section.statusWords[0] !== "idle"
        spacing: Kirigami.Units.smallSpacing

        QQC2.ProgressBar {
            readonly property real total: +section.statusWords[4] || 0
            Layout.fillWidth: true
            visible: section.busy
            indeterminate: section.statusWords[2] !== "download" || total === 0
            from: 0
            to: Math.max(total, 1)
            value: +section.statusWords[3] || 0
        }
        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            color: section.statusWords[0] === "error" ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
            text: {
                const w = section.statusWords;
                const name = section.toolName(w[1]);
                switch (w[0]) {
                case "running":
                    if (w[2] === "unpack")
                        return "Unpacking " + name + "…";
                    return +w[4] > 0 ? "Downloading " + name + ": " + section.gb(+w[3]) + " of " + section.gb(+w[4]) + "…"
                                     : "Getting ready to download " + name + "…";
                case "done":
                    return w[2] + " is installed. Steam lists it after it restarts: return to Game Mode, or quit and start Steam again.";
                case "error":
                    return name + " could not be installed: " + w.slice(2).join(" ");
                default:
                    return "";
                }
            }
        }
    }

    FormCard.FormHeader {
        title: "Installed"
        visible: Backend.protonInstalled.length > 0
        maximumWidth: section.maximumWidth
    }

    FormCard.FormCard {
        visible: Backend.protonInstalled.length > 0
        maximumWidth: section.maximumWidth

        Repeater {
            model: Backend.protonInstalled

            delegate: FormCard.FormTextDelegate {
                id: buildRow

                required property string modelData
                readonly property string build: modelData.split(" ")[1]

                text: build
                description: section.toolName(modelData.split(" ")[0])
                trailing: QQC2.Button {
                    icon.name: "edit-delete"
                    text: "Remove"
                    enabled: !section.busy
                    onClicked: {
                        removeDialog.build = buildRow.build;
                        removeDialog.open();
                    }
                }
            }
        }
    }

    Kirigami.PromptDialog {
        id: removeDialog

        property string build

        title: "Remove " + build + "?"
        subtitle: "Games set to use it need another Proton chosen in their Properties > Compatibility."
        standardButtons: Kirigami.Dialog.NoButton
        customFooterActions: [
            Kirigami.Action {
                text: "Remove"
                icon.name: "edit-delete"
                onTriggered: {
                    Backend.removeProton(removeDialog.build);
                    removeDialog.close();
                }
            },
            Kirigami.Action {
                text: "Cancel"
                icon.name: "dialog-cancel"
                onTriggered: removeDialog.close()
            }
        ]
    }
}
