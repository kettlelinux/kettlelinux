// SPDX-License-Identifier: BSD-3-Clause
// A page section: heading and an optional line of explanation.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

ColumnLayout {
    property alias title: heading.text
    property alias description: desc.text

    Layout.fillWidth: true
    Layout.topMargin: Kirigami.Units.largeSpacing
    spacing: Kirigami.Units.smallSpacing

    Kirigami.Heading {
        id: heading
        Layout.fillWidth: true
        level: 2
        wrapMode: Text.Wrap
    }
    QQC2.Label {
        id: desc
        Layout.fillWidth: true
        visible: text.length > 0
        wrapMode: Text.Wrap
        opacity: 0.8
    }
}
