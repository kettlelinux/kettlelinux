// SPDX-License-Identifier: BSD-3-Clause
// A switch that shows `value` and reports a flip, keeping its binding to `value` afterwards.
import QtQuick
import QtQuick.Layouts

import org.kde.plasma.components as PlasmaComponents3

PlasmaComponents3.Switch {
    id: control

    property bool value

    signal picked(bool on)

    Layout.fillWidth: true
    checked: value
    onToggled: {
        picked(checked);
        checked = Qt.binding(() => control.value);
    }
}
