// SPDX-License-Identifier: BSD-3-Clause
// Power: the desktop's counterpart of Steam's Performance panel and Game Settings, in the
// system tray. Everything goes through kettle-powerd (PowerBackend).
import QtQuick

import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid

import org.kettle.private.power

PlasmoidItem {
    id: root

    readonly property var steam: powerBackend.status.steam ?? ({})

    PowerBackend {
        id: powerBackend
        // collapsed, the tooltip's readings and Desktop Mode kept active in kettle-powerd: each
        // status read has it measure the draw for a while (firmware reads on the AYNs)
        interval: root.expanded ? 1000 : 60000
    }

    Plasmoid.icon: "speedometer"
    Plasmoid.status: powerBackend.available ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.PassiveStatus

    toolTipMainText: "Power"
    toolTipSubText: {
        if (!powerBackend.available)
            return "The power service isn't running"
        const s = powerBackend.status
        const parts = []
        if (steam.profile)
            parts.push(steam.profile)
        if (s.power_w !== undefined && s.power_w !== null)
            parts.push(s.power_w.toFixed(1) + " W")
        if (s.temp_c !== undefined && s.temp_c !== null)
            parts.push(Math.round(s.temp_c) + " °C")
        return parts.join(" · ")
    }

    fullRepresentation: FullRepresentation {
        power: powerBackend
    }
}
