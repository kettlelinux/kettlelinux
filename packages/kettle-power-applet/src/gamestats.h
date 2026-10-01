// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include <QList>
#include <QObject>
#include <QTimer>
#include <qqmlregistration.h>

// The game in front in Game Mode: its frame rate and frame times, from what our mangoapp build
// writes to $XDG_RUNTIME_DIR/kettle-fps about once a second (packages/mangohud 0005), and which
// game it is, from its process (SteamAppId, and the Frame Generation layer loaded or not), as
// the Frame Generation plugin tells.
class GameStats : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    // frames arrived lately, and from a game rather than Steam's own UI
    Q_PROPERTY(bool running READ running NOTIFY changed)
    // Steam's UI is in front (the game, if any, is behind it)
    Q_PROPERTY(bool steamFocused READ steamFocused NOTIFY changed)
    Q_PROPERTY(QString appid READ appid NOTIFY changed)
    Q_PROPERTY(QString name READ name NOTIFY changed)
    // displayed frames per second, over the last second
    Q_PROPERTY(double fps READ fps NOTIFY changed)
    // mean frame time over the last second, ms
    Q_PROPERTY(double frameTime READ frameTime NOTIFY changed)
    // the frame rate of the slowest 1% of frames, over the frame times kept (history)
    Q_PROPERTY(double low1 READ low1 NOTIFY changed)
    // the display's refresh rate, Hz
    Q_PROPERTY(int refresh READ refresh NOTIFY changed)
    // the Frame Generation layer's multiplier for this game; 0: not in use
    Q_PROPERTY(int frameGen READ frameGen NOTIFY changed)
    // displayed frame times, ms, oldest first: the last `history` seconds
    Q_PROPERTY(QList<qreal> frameTimes READ frameTimes NOTIFY changed)
    Q_PROPERTY(int history READ history WRITE setHistory NOTIFY historyChanged)
    // how often the file is read, ms
    Q_PROPERTY(int interval READ interval WRITE setInterval NOTIFY intervalChanged)

public:
    explicit GameStats(QObject *parent = nullptr);

    bool running() const { return m_running; }
    bool steamFocused() const { return m_steamFocused; }
    QString appid() const { return m_appid; }
    QString name() const { return m_name; }
    double fps() const { return m_fps; }
    double frameTime() const { return m_frameTime; }
    double low1() const { return m_low1; }
    int refresh() const { return m_refresh; }
    int frameGen() const { return m_frameGen; }
    QList<qreal> frameTimes() const { return m_frameTimes; }
    int history() const { return m_history; }
    void setHistory(int seconds);
    int interval() const { return m_timer.interval(); }
    void setInterval(int ms);

    // a Steam game's name, from its app manifest; "" if it isn't installed
    Q_INVOKABLE QString nameOf(const QString &appid) const;

Q_SIGNALS:
    void changed();
    void historyChanged();
    void intervalChanged();

private:
    void poll();
    void identify(uint pid);
    void trim();
    void stop();

    QTimer m_timer;
    QString m_path;
    qint64 m_stamp = -1; // the file's time= last read
    uint m_pid = 0;
    bool m_running = false;
    bool m_steamFocused = false;
    QString m_appid;
    QString m_name;
    bool m_layer = false; // the Frame Generation layer is loaded in the game
    double m_fps = 0;
    double m_frameTime = 0;
    double m_low1 = 0;
    int m_refresh = 0;
    int m_frameGen = 0;
    QList<qreal> m_frameTimes;
    int m_history = 10;
};
