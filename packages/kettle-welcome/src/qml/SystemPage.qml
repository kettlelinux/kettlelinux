// SPDX-License-Identifier: BSD-3-Clause
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import org.kettle.welcome

BasePage {
    title: "System"
    heading: "System"

    Section {
        title: "Internal storage"
        description: "Kettle starts from the microSD card. The Kettle Installer copies it to the internal storage, next to Android (dual boot) or with Android kept small, so it runs without the card. It also updates, backs up, restores and removes that installation. Connect the charger first."
    }

    TileGrid {
        Tile {
            iconName: "drive-harddisk"
            title: "Kettle Installer"
            subtitle: "Install, update, back up, restore or remove Kettle on the internal storage."
            onClicked: Backend.launchApp("kettle-installer")
        }
    }

    Section { title: "Apps and information" }

    TileGrid {
        Tile {
            iconName: "plasmadiscover"
            title: "Software"
            subtitle: "Find and install more apps (Discover)."
            onClicked: Backend.launchApp("org.kde.discover")
        }
        Tile {
            iconName: "utilities-system-monitor"
            title: "System Monitor"
            subtitle: "What's using the processor, memory and storage."
            onClicked: Backend.launchApp("org.kde.plasma-systemmonitor")
        }
        Tile {
            iconName: "battery-good"
            title: "Battery"
            subtitle: "Charge, health and power use over time."
            onClicked: Backend.openSettings("kcm_energyinfo")
        }
        Tile {
            iconName: "help-about"
            title: "About this system"
            subtitle: "Versions of the system, the desktop and the hardware."
            onClicked: Backend.openSettings("kcm_about-distro")
        }
    }
}
