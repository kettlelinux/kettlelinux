// SPDX-License-Identifier: BSD-3-Clause
// Tiles in as many columns as fit.
import QtQuick
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

GridLayout {
    // sized from the page, not from the tiles (whose maximum width follows cellWidth)
    readonly property real availableWidth: parent ? parent.width : 0
    // one column's width: a tile alone in its section doesn't stretch across the page (Tile)
    readonly property real cellWidth: (availableWidth - columnSpacing * (columns - 1)) / columns

    Layout.fillWidth: true
    columns: Math.max(1, Math.floor(availableWidth / (Kirigami.Units.gridUnit * 17)))
    columnSpacing: Kirigami.Units.largeSpacing
    rowSpacing: Kirigami.Units.largeSpacing
}
