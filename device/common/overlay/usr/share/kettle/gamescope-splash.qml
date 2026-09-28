// Kettle Linux: the boot splash, shown by Game Mode (gamescope) until Steam's own screen is up
// (/usr/lib/kettle/gamescope-splash). Same art and layout as the plymouth theme
// (/usr/share/plymouth/themes/kettle/kettle.script), so the logo carries on from the boot
// splash: kettle, rising steam, name; the progress line moves to show that it is still working.
import QtQuick
import QtQuick.Window

Window {
    id: win
    visibility: Window.FullScreen
    color: "black"
    title: "Kettle Linux"

    readonly property string art: "file:///usr/share/plymouth/themes/kettle/"
    // drawn for a 1920x1080 screen, scaled from there
    readonly property real s: Math.min(width / 1920, height / 1080)
    property int frame: 0   // 50 Hz, as the plymouth theme's refresh function

    Timer {
        interval: 20; running: true; repeat: true
        onTriggered: win.frame++
    }

    // kettle, 36 gap, wordmark, 44 gap, progress line; centred as one group, a little low
    Item {
        id: group
        width: parent.width
        height: (320 + 36 + 48 + 44 + 4) * win.s
        y: (win.height - height) / 2 + 24 * win.s

        Image {
            id: kettle
            source: win.art + "kettle.png"
            width: 320 * win.s; height: 320 * win.s
            x: (group.width - width) / 2
            smooth: true
        }

        Repeater {   // three wisps of steam from the spout, as in the theme
            model: 3
            Image {
                readonly property real t: ((win.frame + index * 50) % 150) / 150
                source: win.art + "steam.png"
                width: 60 * win.s; height: 180 * win.s
                x: kettle.x + (292 - 30 + index * 6) * win.s + Math.sin(t * Math.PI * 2 + index * 2.1) * 7 * win.s
                y: kettle.y + (138 - 170 - t * 90) * win.s
                opacity: Math.sin(t * Math.PI) * 0.7
                z: -1
                smooth: true
            }
        }

        Image {
            source: win.art + "wordmark.png"
            width: 332 * win.s; height: 48 * win.s
            x: (group.width - width) / 2
            y: kettle.height + 36 * win.s
            smooth: true
        }

        Image {
            id: track
            source: win.art + "progress-track.png"
            width: 240 * win.s; height: 4 * win.s
            x: (group.width - width) / 2
            y: kettle.height + (36 + 48 + 44) * win.s
            clip: true

            Image {   // a short segment of the heat-coloured line sweeping across
                source: win.art + "progress-fill.png"
                width: parent.width / 3; height: parent.height
                x: (Math.sin(win.frame / 150 * Math.PI * 2) + 1) / 2 * (parent.width - width)
                sourceClipRect: Qt.rect(x / win.s, 0, 80, 4)
            }
        }
    }
}
