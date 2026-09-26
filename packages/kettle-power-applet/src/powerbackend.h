// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include <QObject>
#include <QTimer>
#include <QVariantMap>
#include <qqmlregistration.h>

#include <functional>

class QDBusMessage;

// kettle-powerd (org.kettlelinux.Power1, system bus) for the desktop's Power applet.
//
// Desktop Mode is a "game" of its own to kettle-powerd: the applet makes "desktop" the active
// game, so fan and CPU settings changed here are Desktop Mode's and Game Mode's all-games
// settings stay as they are (until Desktop Mode has its own, it uses those). Steam's values
// (performance profile, TDP limit, GPU clock) are device-wide in kettle-powerd; Steam sets its
// own again in Game Mode, so the ones picked here are kept in kettle-powerrc and set again when
// the desktop starts.
class PowerBackend : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(bool available READ available NOTIFY availableChanged)
    // GetInfo: clusters, gpu_mhz, gpu_manual_mhz, profiles, tdp, fan, default_curve, ...
    Q_PROPERTY(QVariantMap info READ info NOTIFY infoChanged)
    // GetStatus: readings, and Steam's values under "steam"
    Q_PROPERTY(QVariantMap status READ status NOTIFY statusChanged)
    // Desktop Mode's fan and CPU settings: {fan: {mode, curve, fixed}, cpu: {...}}
    Q_PROPERTY(QVariantMap settings READ settings NOTIFY settingsChanged)
    // false: Desktop Mode uses the all-games settings
    Q_PROPERTY(bool customSettings READ customSettings NOTIFY settingsChanged)
    // how often status is read, in ms
    Q_PROPERTY(int interval READ interval WRITE setInterval NOTIFY intervalChanged)

public:
    explicit PowerBackend(QObject *parent = nullptr);
    ~PowerBackend() override;

    bool available() const { return m_available; }
    QVariantMap info() const { return m_info; }
    QVariantMap status() const { return m_status; }
    QVariantMap settings() const { return m_settings; }
    bool customSettings() const { return m_custom; }
    int interval() const { return m_timer.interval(); }
    void setInterval(int ms);

    // one of Steam's values, by its GetStatus name: profile, tdp, gpu_level, gpu_clock,
    // fan_control, charge_limit
    Q_INVOKABLE void setSteam(const QString &key, const QVariant &value);
    // Desktop Mode's own fan and CPU settings
    Q_INVOKABLE void setSettings(const QVariantMap &settings);
    // back to the all-games settings
    Q_INVOKABLE void resetSettings();

Q_SIGNALS:
    void availableChanged();
    void infoChanged();
    void statusChanged();
    void settingsChanged();
    void intervalChanged();

private:
    // done(ok, the string a Get* method returns)
    void call(const QString &method, const QVariantList &args, std::function<void(bool, const QString &)> done = {});
    void callMessage(const QDBusMessage &msg, std::function<void(bool, const QString &)> done);
    void setSteamProperty(const QString &key, const QVariant &value);
    void setAvailable(bool available);
    void tick();
    void connectDaemon();
    void readGame();

    QTimer m_timer;
    bool m_available = false;
    bool m_connected = false; // info read, Desktop Mode active and its values set
    bool m_busy = false; // a status read or connect is under way
    QVariantMap m_info;
    QVariantMap m_status;
    QVariantMap m_settings;
    bool m_custom = false;
};
