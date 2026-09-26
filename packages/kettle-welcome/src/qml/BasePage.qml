// SPDX-License-Identifier: BSD-3-Clause
// A scrolling page with a big heading and a column of content, kept to a readable width.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    property alias heading: headingItem.text
    property alias description: descItem.text
    default property alias content: column.data

    padding: Kirigami.Units.gridUnit

    ColumnLayout {
        id: column
        spacing: Kirigami.Units.largeSpacing

        Kirigami.Heading {
            id: headingItem
            Layout.fillWidth: true
            visible: text.length > 0
            level: 1
            font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.8
            wrapMode: Text.Wrap
        }
        QQC2.Label {
            id: descItem
            Layout.fillWidth: true
            visible: text.length > 0
            wrapMode: Text.Wrap
        }
    }
}
