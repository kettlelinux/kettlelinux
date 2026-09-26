// SPDX-License-Identifier: BSD-3-Clause
// The controller as mouse and keyboard in the desktop (kettle-desktop-controller).
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import org.kettle.welcome

BasePage {
    id: page

    title: "Controls"
    heading: "Desktop controls"
    description: "The built-in controller works as a mouse and keyboard here, so you don't need to plug anything in. Hold <b>Select + Start</b> to turn that off, for example for a game started from the desktop that wants the controller, and hold it again to turn it back on."

    readonly property var controls: [
        ["Left stick", "Move the pointer"],
        ["Right stick", "Scroll"],
        ["A or R2", "Left click (hold to drag)"],
        ["B or L2", "Right click"],
        ["R3", "Middle click"],
        ["R1 (hold)", "Precise pointer"],
        ["X or Home", "On-screen keyboard"],
        ["Y", "Enter"],
        ["D-pad", "Arrow keys"],
        ["L1", "Escape"],
        ["Start", "Application menu"],
        ["Select", "Overview"]
    ]

    Kirigami.AbstractCard {
        Layout.fillWidth: true

        contentItem: GridLayout {
            columns: page.width > Kirigami.Units.gridUnit * 40 ? 4 : 2
            columnSpacing: Kirigami.Units.gridUnit
            rowSpacing: Kirigami.Units.largeSpacing

            Repeater {
                model: page.controls

                delegate: RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.columnSpan: 2
                    spacing: Kirigami.Units.largeSpacing

                    QQC2.Label {
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 6
                        text: modelData[0]
                        font.bold: true
                    }
                    QQC2.Label {
                        Layout.fillWidth: true
                        text: modelData[1]
                        wrapMode: Text.Wrap
                    }
                }
            }
        }
    }

    Section { title: "Good to know" }

    TileGrid {
        Tile {
            iconName: "input-keyboard-virtual"
            title: "On-screen keyboard"
            subtitle: "Opens by itself whenever a text field is selected, and from the keyboard icon in the system tray."
            onClicked: Backend.openSettings("kcm_virtualkeyboard")
        }
        Tile {
            iconName: "gaming-return"
            title: "Return to Game Mode"
            subtitle: "Back to Steam's handheld interface. The Return to Gaming Mode icon on the desktop does the same."
            onClicked: Backend.returnToGameMode()
        }
    }
}
