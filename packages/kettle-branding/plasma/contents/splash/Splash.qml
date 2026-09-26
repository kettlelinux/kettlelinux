// Kettle Linux splash screen (KSplash). The same picture as the boot splash (kettle.script),
// so boot runs plymouth -> Plasma without a jump: a copper kettle on black, steam rising from
// the spout, and a progress line that follows Plasma's startup stages. Plain QtQuick; the art
// is laid out for 1920x1080 like the boot splash and scaled to the screen.
import QtQuick

Rectangle {
    id: root
    color: "black"
    width: 1920
    height: 1080

    // set by ksplashqml as Plasma starts up
    property int stage
    readonly property real progress: Math.min(stage / 5, 1)

    readonly property real s: Math.min(width / 1920, height / 1080)

    // same group layout as kettle.script: kettle, 36 gap, wordmark, 44 gap, progress line
    readonly property real groupTop: (height - (320 + 36 + 48 + 44 + 4) * s) / 2 + 24 * s

    FrameAnimation {
        id: clock
        running: true
    }

    Item {
        id: content
        anchors.fill: parent
        opacity: 0

        OpacityAnimator on opacity {
            from: 0
            to: 1
            duration: 400
            easing.type: Easing.OutQuad
        }

        Image {
            source: "images/glow.png"
            width: 840 * root.s
            height: 600 * root.s
            x: kettle.x + 160 * root.s - width / 2
            y: kettle.y + 210 * root.s - height / 2
            opacity: 0.16 * (1 + 0.15 * Math.sin(clock.elapsedTime * 3.2))
            smooth: true
        }

        // three wisps, one every second, each rising for three seconds (kettle.script's timing)
        Repeater {
            model: 3

            Image {
                required property int index
                readonly property real t: ((clock.elapsedTime + index) % 3) / 3

                source: "images/steam.png"
                width: 60 * root.s
                height: 180 * root.s
                x: kettle.x + 292 * root.s - 30 * root.s
                   + Math.sin(t * Math.PI * 2 + index * 2.1) * 7 * root.s + index * 6 * root.s
                y: kettle.y + 138 * root.s - 170 * root.s - t * 90 * root.s
                opacity: Math.sin(t * Math.PI) * 0.7
                smooth: true
                mipmap: true
            }
        }

        Image {
            id: kettle
            source: "images/kettle.png"
            width: 320 * root.s
            height: 320 * root.s
            x: (root.width - width) / 2
            y: root.groupTop
            smooth: true
            mipmap: true
        }

        Image {
            id: wordmark
            source: "images/wordmark.png"
            width: 332 * root.s
            height: 48 * root.s
            x: (root.width - width) / 2
            y: kettle.y + kettle.height + 36 * root.s
            smooth: true
            mipmap: true
        }

        Rectangle {
            id: track
            width: 240 * root.s
            height: 4 * root.s
            radius: height / 2
            x: (root.width - width) / 2
            y: wordmark.y + wordmark.height + 44 * root.s
            color: "#24ffffff"

            Rectangle {
                height: parent.height
                width: parent.width * root.progress
                radius: height / 2
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: "#d9502a" }
                    GradientStop { position: 1; color: "#ffc46b" }
                }

                Behavior on width {
                    NumberAnimation { duration: 600; easing.type: Easing.OutCubic }
                }
            }
        }
    }
}
