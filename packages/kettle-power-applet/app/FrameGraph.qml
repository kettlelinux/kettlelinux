// SPDX-License-Identifier: BSD-3-Clause
// Frame times over the last seconds, oldest at the left, each frame as wide as it was long: a
// flat line is smooth, a spike is a stutter. The dashed line is one refresh of the display.
import QtQuick

import org.kde.kirigami as Kirigami

Canvas {
    id: graph

    // ms, oldest first
    property var times: []
    // the display's refresh rate, Hz (0: unknown)
    property int refresh: 0
    // seconds across
    property int seconds: 10

    readonly property color lineColor: Kirigami.Theme.highlightColor
    readonly property color guideColor: Kirigami.Theme.disabledTextColor

    onTimesChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()

    onPaint: {
        const ctx = getContext("2d");
        ctx.reset();
        const t = times;
        if (!t || !t.length)
            return;
        const target = refresh > 0 ? 1000 / refresh : 16.7;
        // twice a refresh at least, so a steady game sits in the lower half; 100 ms at most
        const top = Math.min(100, Math.max(target * 2, ...t) * 1.1);
        const y = ms => height - Math.min(ms, top) / top * height;
        const span = seconds * 1000;

        ctx.strokeStyle = guideColor;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(0, y(target));
        ctx.lineTo(width, y(target));
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.strokeStyle = lineColor;
        ctx.lineWidth = 2;
        ctx.beginPath();
        let total = t.reduce((a, b) => a + b, 0);
        let x = width - Math.min(total, span) / span * width;
        ctx.moveTo(x, y(t[0]));
        for (const ms of t) {
            ctx.lineTo(x, y(ms));
            x += ms / span * width;
            ctx.lineTo(x, y(ms));
        }
        ctx.stroke();
    }
}
