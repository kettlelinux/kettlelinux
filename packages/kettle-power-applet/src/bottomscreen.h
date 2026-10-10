// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include <QFileSystemWatcher>
#include <QObject>
#include <QTimer>
#include <qqmlregistration.h>

// The bottom screen's brightness and refresh rate in Game Mode, the Thor's Screens settings
// (~/.config/kettle/bottom-screen.json: "brightness", percent, which the device's
// bottom-brightness service applies; "refresh_hz", 60 or 30, which bottom-screen starts at and
// this sets live on the bottom screen's gamescope). Device Settings > Screens sets the same file;
// a change made there shows here.
class BottomScreen : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    // on the bottom screen's shell in Game Mode (bottom-shell sets KETTLE_BOTTOM_SHELL), on a
    // device whose bottom panel's backlight is bottom-panel
    Q_PROPERTY(bool available READ available CONSTANT)
    Q_PROPERTY(int brightness READ brightness WRITE setBrightness NOTIFY brightnessChanged)
    Q_PROPERTY(int refreshHz READ refreshHz WRITE setRefreshHz NOTIFY refreshHzChanged)
    // Steam has dimmed the screens for idleness: bottom-brightness keeps
    // $XDG_RUNTIME_DIR/kettle-bottom-dimmed while it lasts
    Q_PROPERTY(bool dimmed READ dimmed NOTIFY dimmedChanged)

public:
    explicit BottomScreen(QObject *parent = nullptr);

    bool available() const { return m_available; }
    int brightness() const { return m_brightness; }
    int refreshHz() const { return m_refreshHz; }
    bool dimmed() const { return m_dimmed; }
    void setBrightness(int percent);
    void setRefreshHz(int hz);

Q_SIGNALS:
    void brightnessChanged();
    void refreshHzChanged();
    void dimmedChanged();

private:
    void load();
    void readDimmed();
    // the file with one setting changed, the others as they are
    void save(const QString &key, int value);

    QTimer m_timer;
    QFileSystemWatcher m_watcher;
    QString m_path;
    QString m_dimmedPath;
    bool m_available = false;
    int m_brightness = 70;
    int m_refreshHz = 60;
    bool m_dimmed = false;
};
