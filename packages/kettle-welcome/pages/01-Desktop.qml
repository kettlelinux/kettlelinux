/*
 * Desktop Mode on the Portal: the gamepad controls (kettle-desktop-controller), the on-screen
 * keyboard, the way back to Game Mode, and the Kettle Installer (internal storage).
 *
 * SPDX-License-Identifier: BSD-3-Clause
 */

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.kirigamiaddons.formcard as FormCard

import org.kde.plasma.welcome

GenericPage {
    id: page

    heading: "Desktop Mode"
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

    QQC2.ScrollView {
        id: scroll
        anchors.fill: parent
        contentWidth: availableWidth
        QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff

        ColumnLayout {
            width: scroll.availableWidth
            spacing: 0

            FormCard.FormHeader {
                title: "Controller"
            }

            FormCard.FormCard {
                GridLayout {
                    Layout.fillWidth: true
                    Layout.margins: Kirigami.Units.largeSpacing
                    columns: page.width > Kirigami.Units.gridUnit * 36 ? 4 : 2
                    columnSpacing: Kirigami.Units.largeSpacing
                    rowSpacing: Kirigami.Units.smallSpacing

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

            FormCard.FormHeader {
                title: "Good to know"
            }

            FormCard.FormCard {
                FormCard.FormTextDelegate {
                    icon.name: "input-keyboard-virtual"
                    text: "On-screen keyboard"
                    description: "Opens by itself whenever a text field is selected, and from the keyboard icon in the system tray."
                }
                FormCard.FormDelegateSeparator {}
                FormCard.FormTextDelegate {
                    icon.name: "gaming-return"
                    text: "Back to Game Mode"
                    description: "Open Return to Gaming Mode on the desktop."
                }
            }

            FormCard.FormHeader {
                title: "Internal storage"
            }

            FormCard.FormCard {
                FormCard.FormButtonDelegate {
                    icon.name: "drive-harddisk"
                    text: "Kettle Installer"
                    description: "Copies Kettle from the microSD card to the internal storage, next to Android (dual boot) or with Android kept small, so it runs without the card. It also updates, backs up, restores and removes that installation. Connect the charger first."
                    onClicked: Controller.launchApp("kettle-installer")
                }
            }

            Item {
                Layout.preferredHeight: Kirigami.Units.largeSpacing
            }
        }
    }
}
