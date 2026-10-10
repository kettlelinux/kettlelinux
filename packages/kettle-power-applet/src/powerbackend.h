// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include <QObject>
#include <QTimer>
#include <QVariantMap>
#include <qqmlregistration.h>

#include <functional>

class QDBusMessage;

// kettle-powerd (org.kettlelinux.Power1, system bus) for the desktop's Power applet and the
// Performance app.
//
// mode Desktop (the applet, and the app in Desktop Mode): Desktop Mode is a "game" of its own to
// kettle-powerd: the backend makes "desktop" the active game, so fan and CPU settings changed
// here are Desktop Mode's and Game Mode's all-games settings stay as they are (until Desktop Mode
// has its own, it uses those). Steam's values (performance profile, TDP limit, GPU clock) are
// device-wide in kettle-powerd; Steam sets its own again in Game Mode, so the ones picked here
// are kept in kettle-powerrc and set again when the desktop starts.
//
// mode GameMode (the app on the Thor's bottom screen, next to Steam): nothing is made the active
// game (Device Settings says which game runs); the settings shown are the running game's, as in
// Game Settings: its own when it has them, else the all-games ones, which are the ones edited
// then. Steam's values are set in kettle-powerd, and aren't kept for Desktop Mode; the Power
// plugin sets them in Steam too (its steamSync.ts), so Steam's sliders follow. What they are is
// always read back from kettle-powerd, so a change made in Steam shows here.
class PowerBackend : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(Mode mode READ mode WRITE setMode NOTIFY modeChanged)
    Q_PROPERTY(bool available READ available NOTIFY availableChanged)
    // GetInfo: clusters, gpu_mhz, gpu_manual_mhz, profiles, tdp, fan, default_curve, ...
    Q_PROPERTY(QVariantMap info READ info NOTIFY infoChanged)
    // GetStatus: readings, and Steam's values under "steam"
    Q_PROPERTY(QVariantMap status READ status NOTIFY statusChanged)
    // the fan and CPU settings in use: {fan: {mode, curve, fixed}, cpu: {...}}; Desktop Mode's,
    // or in GameMode the running game's
    Q_PROPERTY(QVariantMap settings READ settings NOTIFY settingsChanged)
    // false: Desktop Mode (the running game) uses the all-games settings
    Q_PROPERTY(bool customSettings READ customSettings NOTIFY settingsChanged)
    // GameMode: the running game's appid, "" with none
    Q_PROPERTY(QString activeGame READ activeGame NOTIFY activeGameChanged)
    // how often status is read, in ms
    Q_PROPERTY(int interval READ interval WRITE setInterval NOTIFY intervalChanged)
    // false: no reading (and no redrawing) until it is true again, when it reads at once
    Q_PROPERTY(bool active READ active WRITE setActive NOTIFY activeChanged)

public:
    enum Mode { Desktop, GameMode };
    Q_ENUM(Mode)

    explicit PowerBackend(QObject *parent = nullptr);
    ~PowerBackend() override;

    Mode mode() const { return m_mode; }
    void setMode(Mode mode);
    QString activeGame() const { return m_activeGame; }
    bool available() const { return m_available; }
    QVariantMap info() const { return m_info; }
    QVariantMap status() const { return m_status; }
    QVariantMap settings() const { return m_settings; }
    bool customSettings() const { return m_custom; }
    int interval() const { return m_timer.interval(); }
    void setInterval(int ms);
    bool active() const { return m_timer.isActive(); }
    void setActive(bool active);

    // one of Steam's values, by its GetStatus name: profile, tdp, gpu_level, gpu_clock,
    // fan_control, charge_limit
    Q_INVOKABLE void setSteam(const QString &key, const QVariant &value);
    // the fan and CPU settings shown (settings): Desktop Mode's own, or in GameMode the running
    // game's own if it has them, else the all-games ones
    Q_INVOKABLE void setSettings(const QVariantMap &settings);
    // back to the all-games settings (GameMode, with no game settings of its own: the all-games
    // settings back to their defaults)
    Q_INVOKABLE void resetSettings();
    // GameMode: the running game gets settings of its own (a copy of those shown), or goes back
    // to the all-games ones
    Q_INVOKABLE void setGameOnly(bool on);
    // charging, device-wide, as Device Settings > Power sets it: a speed by name (one of
    // info.charge_speeds, or "Custom" where info.charge_custom says the current can be set), that
    // current in µA, and the fan's speed while the device sleeps on its charger (0: off)
    Q_INVOKABLE void setChargeSpeed(const QString &name);
    Q_INVOKABLE void setChargeCurrent(int ua);
    Q_INVOKABLE void setSleepFan(int pct);

Q_SIGNALS:
    void modeChanged();
    void activeGameChanged();
    void availableChanged();
    void infoChanged();
    void statusChanged();
    void settingsChanged();
    void intervalChanged();
    void activeChanged();

private:
    // done(ok, the string a Get* method returns)
    void call(const QString &method, const QVariantList &args, std::function<void(bool, const QString &)> done = {});
    void callMessage(const QDBusMessage &msg, std::function<void(bool, const QString &)> done);
    void setSteamProperty(const QString &key, const QVariant &value);
    void setAvailable(bool available);
    void tick();
    void connectDaemon();
    void readGame();
    // the game whose settings are read: Desktop Mode, or the running game (all games with none)
    QString gameKey() const;
    // the one setSettings writes
    QString editKey() const;

    QTimer m_timer;
    Mode m_mode = Desktop;
    QString m_activeGame;
    bool m_available = false;
    bool m_connected = false; // info read, Desktop Mode active and its values set
    bool m_busy = false; // a status read or connect is under way
    QVariantMap m_info;
    QVariantMap m_status;
    QVariantMap m_settings;
    bool m_custom = false;
};
