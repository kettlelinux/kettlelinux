// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include <QObject>
#include <QTimer>
#include <qqmlregistration.h>

// The bottom screen's brightness in Game Mode, the Thor's Screens setting
// (~/.config/kettle/bottom-screen.json, "brightness", percent), which the device's
// bottom-brightness service applies. Quick Access > Screens sets the same file; a change made
// there shows here.
class BottomScreen : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    // on the bottom screen's shell in Game Mode (bottom-shell sets KETTLE_BOTTOM_SHELL), on a
    // device whose bottom panel's backlight is bottom-panel
    Q_PROPERTY(bool available READ available CONSTANT)
    Q_PROPERTY(int brightness READ brightness WRITE setBrightness NOTIFY brightnessChanged)

public:
    explicit BottomScreen(QObject *parent = nullptr);

    bool available() const { return m_available; }
    int brightness() const { return m_brightness; }
    void setBrightness(int percent);

Q_SIGNALS:
    void brightnessChanged();

private:
    void load();

    QTimer m_timer;
    QString m_path;
    bool m_available = false;
    int m_brightness = 70;
};
