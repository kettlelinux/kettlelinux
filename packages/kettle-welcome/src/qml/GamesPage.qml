// SPDX-License-Identifier: BSD-3-Clause
// Games outside Steam: the preinstalled launchers, how Windows games run, getting them into
// Game Mode.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import org.kettle.welcome

BasePage {
    id: page

    signal navigate(string name)

    title: "Games"
    heading: "Games outside Steam"
    description: "Two game launchers come with Kettle, for your libraries from other stores and for games you already own."

    TileGrid {
        Tile {
            iconName: "com.heroicgameslauncher.hgl"
            title: "Heroic Games Launcher"
            subtitle: "Your Epic Games Store, GOG and Amazon Prime Gaming libraries: sign in, then install and play."
            onClicked: Backend.launchApp("com.heroicgameslauncher.hgl")
        }
        Tile {
            iconName: "net.lutris.Lutris"
            title: "Lutris"
            subtitle: "Everything else: install scripts for thousands of games from lutris.net, your own Windows games and their installers, and emulators, all in one library."
            onClicked: Backend.launchApp("net.lutris.Lutris")
        }
        Tile {
            iconName: "steam"
            title: "Steam"
            subtitle: "Steam's desktop client, for adding games from other launchers to your library."
            onClicked: Backend.launchApp("steam")
        }
    }

    Section {
        title: "Play them in Game Mode"
        description: "In Steam on the desktop, choose Add a Game > Add a Non-Steam Game. Or add whole libraries at once, with artwork, with BoilR. The games then show up in your Steam library in Game Mode."
    }

    TileGrid {
        Tile {
            iconName: "download"
            title: "Get BoilR"
            subtitle: "From Gaming Extras, with emulators and other tools."
            onClicked: page.navigate("extras")
        }
    }

    Section {
        title: "How Windows games run"
        description: "Through Wine, with FEX translating their x86 code for this device's ARM processor and DXVK and vkd3d-proton turning Direct3D into Vulkan: the same way Steam runs Windows games here. How well a game runs depends on the game: older and lighter games fit best. Online games with anti-cheat (EasyAntiCheat, BattlEye) usually don't work."
    }
}
