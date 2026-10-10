// SPDX-License-Identifier: BSD-3-Clause
// Gaming Extras: Battle.net, Blizzard's launcher, added to Steam with Proton-CachyOS by
// welcome-battlenet, which Game Mode's Game Stores (kettle-decky-plugins stores) uses too, so both
// show the same Steam entry. Steam has to be running to add it.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.kirigamiaddons.formcard as FormCard

import org.kettle.welcome

ColumnLayout {
    id: section

    property real maximumWidth

    readonly property var s: Backend.battlenet
    readonly property bool done: s.in_steam === true && s.ready === true

    Layout.fillWidth: true
    spacing: 0

    Component.onCompleted: Backend.refreshBattlenet()

    // picks up Steam starting, Proton-CachyOS arriving and the installer finishing
    Timer {
        interval: 5000
        repeat: true
        running: section.visible
        onTriggered: Backend.refreshBattlenet()
    }

    FormCard.FormHeader {
        title: "Game stores"
        maximumWidth: section.maximumWidth
    }

    FormCard.FormCard {
        maximumWidth: section.maximumWidth

        FormCard.FormTextDelegate {
            text: "Battle.net" + (section.done ? "  (in Steam)" : "")
            description: {
                let d = "Blizzard's launcher, for Blizzard and Activision games you own there, added to your Steam library and run with Proton-CachyOS. Its installer comes from battle.net. The launcher is slow to start on this device, and games with anti-cheat may refuse to run.";
                if (!section.s.proton)
                    d += "\nInstall Proton-CachyOS first (below), then restart Steam.";
                else if (!section.s.steam)
                    d += "\nStart Steam first: Battle.net is added to its library.";
                else if (section.s.in_steam && !section.s.ready)
                    d += "\nThe installer is in your Steam library as Battle.net. Once it finishes, the same entry starts Battle.net.";
                else if (section.done)
                    d += "\nIn your Steam library. Sign in there, then install your games from Battle.net.";
                return d;
            }
            trailing: QQC2.Button {
                visible: !section.done
                icon.name: "download"
                text: Backend.battlenetBusy ? "Installing…" : section.s.in_steam ? "Run installer again" : "Install"
                enabled: !Backend.battlenetBusy && !!section.s.proton && section.s.steam === true
                onClicked: Backend.installBattlenet()
            }
        }
    }

    QQC2.Label {
        Layout.fillWidth: true
        Layout.maximumWidth: section.maximumWidth
        Layout.alignment: Qt.AlignHCenter
        Layout.topMargin: Kirigami.Units.smallSpacing
        visible: Backend.battlenetError !== ""
        wrapMode: Text.Wrap
        color: Kirigami.Theme.negativeTextColor
        text: "Battle.net could not be installed: " + Backend.battlenetError
    }
}
