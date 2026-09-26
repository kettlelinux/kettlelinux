/*
 * Games outside Steam: the preinstalled launchers (Heroic, Lutris), how Windows games run
 * (ARM64EC Wine with FEX), and how to get them into Game Mode.
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

    heading: "Games Outside Steam"
    description: "Two game launchers come with Kettle, for your libraries from other stores and for games you already own."

    QQC2.ScrollView {
        id: scroll
        anchors.fill: parent
        contentWidth: availableWidth
        QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff

        ColumnLayout {
            width: scroll.availableWidth
            spacing: 0

            FormCard.FormHeader {
                title: "Launchers"
            }

            FormCard.FormCard {
                FormCard.FormButtonDelegate {
                    icon.name: "com.heroicgameslauncher.hgl"
                    text: "Heroic Games Launcher"
                    description: "Your Epic Games Store, GOG and Amazon Prime Gaming libraries: sign in, then install and play."
                    onClicked: Controller.launchApp("com.heroicgameslauncher.hgl")
                }
                FormCard.FormDelegateSeparator {}
                FormCard.FormButtonDelegate {
                    icon.name: "net.lutris.Lutris"
                    text: "Lutris"
                    description: "Everything else: install scripts for thousands of games from lutris.net, your own Windows games and their installers, and emulators, all in one library."
                    onClicked: Controller.launchApp("net.lutris.Lutris")
                }
            }

            FormCard.FormHeader {
                title: "Good to know"
            }

            FormCard.FormCard {
                FormCard.FormTextDelegate {
                    icon.name: "wine"
                    text: "Windows games"
                    description: "They run through Wine, with FEX translating their x86 code for this device's ARM processor, the same way Steam runs Windows games here. How well a game runs depends on the game: older and lighter games fit best. Online games with anti-cheat (EasyAntiCheat, BattlEye) usually don't work."
                }
                FormCard.FormDelegateSeparator {}
                FormCard.FormTextDelegate {
                    icon.name: "gaming-return"
                    text: "Play them in Game Mode"
                    description: "In Steam on the desktop, choose Add a Game > Add a Non-Steam Game, or add a whole library at once with BoilR from Gaming Extras (next page). The games then show up in your Steam library in Game Mode."
                }
            }

            Item {
                Layout.preferredHeight: Kirigami.Units.largeSpacing
            }
        }
    }
}
