// SPDX-License-Identifier: BSD-3-Clause
#include "powerbackend.h"

#include <QDBusConnection>
#include <QDBusMessage>
#include <QDBusPendingCallWatcher>
#include <QDBusVariant>
#include <QJsonDocument>
#include <QJsonObject>

#include <KConfigGroup>
#include <KSharedConfig>

namespace
{
const QString service = QStringLiteral("org.kettlelinux.Power1");
const QString path = QStringLiteral("/org/kettlelinux/Power1");
const QString desktop = QStringLiteral("desktop"); // Desktop Mode's key among the games

struct SteamProperty {
    const char *key; // name in GetStatus's "steam"
    const char *iface;
    const char *name;
    char type; // D-Bus type: s, u or i
    bool desktop; // kept for Desktop Mode (kettle-powerrc)
};

// set again in this order when the desktop starts: the clock before the level that uses it
const SteamProperty steamProperties[] = {
    {"profile", "PerformanceProfile1", "PerformanceProfile", 's', true},
    {"tdp", "TdpLimit1", "TdpLimit", 'u', true},
    {"gpu_clock", "GpuPerformanceLevel1", "ManualGpuClock", 'u', true},
    {"gpu_level", "GpuPerformanceLevel1", "GpuPerformanceLevel", 's', true},
    {"fan_control", "FanControl1", "FanControlState", 'u', false},
    {"charge_limit", "BatteryChargeLimit1", "MaxChargeLevel", 'i', false},
};

const SteamProperty *steamProperty(const QString &key)
{
    for (const auto &p : steamProperties) {
        if (key == QLatin1String(p.key))
            return &p;
    }
    return nullptr;
}

// KETTLE_POWER_BUS=session: a kettle-powerd on the session bus (testing, as the daemon has it)
QDBusConnection bus()
{
    return qEnvironmentVariable("KETTLE_POWER_BUS") == QLatin1String("session") ? QDBusConnection::sessionBus()
                                                                                : QDBusConnection::systemBus();
}

KConfigGroup desktopValues()
{
    return KSharedConfig::openConfig(QStringLiteral("kettle-powerrc"))->group(QStringLiteral("Desktop"));
}

QVariantMap parse(const QString &json)
{
    return QJsonDocument::fromJson(json.toUtf8()).object().toVariantMap();
}

// kettle-powerd isn't there (as opposed to turning down a value)
bool unreachable(const QDBusMessage &reply)
{
    switch (QDBusError(reply).type()) {
    case QDBusError::ServiceUnknown:
    case QDBusError::NoReply:
    case QDBusError::Timeout:
    case QDBusError::TimedOut:
    case QDBusError::Disconnected:
    case QDBusError::NoServer:
        return true;
    default:
        return reply.errorName().startsWith(QLatin1String("org.freedesktop.DBus.Error.Spawn"));
    }
}
}

PowerBackend::PowerBackend(QObject *parent)
    : QObject(parent)
{
    m_timer.setInterval(5000);
    connect(&m_timer, &QTimer::timeout, this, &PowerBackend::tick);
    m_timer.start();
    QTimer::singleShot(0, this, &PowerBackend::tick);
}

PowerBackend::~PowerBackend()
{
    // the applet is gone (removed, or the desktop ends): back to the all-games settings
    if (m_connected) {
        QDBusMessage msg = QDBusMessage::createMethodCall(service, path, service, QStringLiteral("SetActiveGame"));
        msg.setArguments({QString()});
        bus().call(msg, QDBus::Block, 500);
    }
}

void PowerBackend::setInterval(int ms)
{
    if (ms == m_timer.interval())
        return;
    const bool sooner = ms < m_timer.interval();
    m_timer.setInterval(ms);
    Q_EMIT intervalChanged();
    if (sooner)
        tick();
}

void PowerBackend::call(const QString &method, const QVariantList &args, std::function<void(bool, const QString &)> done)
{
    QDBusMessage msg = QDBusMessage::createMethodCall(service, path, service, method);
    msg.setArguments(args);
    callMessage(msg, std::move(done));
}

void PowerBackend::callMessage(const QDBusMessage &msg, std::function<void(bool, const QString &)> done)
{
    auto *watcher = new QDBusPendingCallWatcher(bus().asyncCall(msg, 5000), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this, [this, watcher, done] {
        watcher->deleteLater();
        const QDBusMessage reply = watcher->reply();
        const bool ok = reply.type() != QDBusMessage::ErrorMessage;
        if (ok) {
            setAvailable(true);
        } else {
            const bool gone = unreachable(reply);
            if (!gone || m_available) // once, not on every poll while it's away
                qWarning("kettle-power-applet: %s: %s", qPrintable(reply.errorName()), qPrintable(reply.errorMessage()));
            if (gone) {
                m_connected = false; // it may come back without Desktop Mode's settings
                setAvailable(false);
            }
        }
        if (done)
            done(ok, ok ? reply.arguments().value(0).toString() : QString());
    });
}

void PowerBackend::setAvailable(bool available)
{
    if (available == m_available)
        return;
    m_available = available;
    Q_EMIT availableChanged();
}

void PowerBackend::tick()
{
    if (m_busy)
        return;
    if (!m_connected) {
        connectDaemon();
        return;
    }
    m_busy = true;
    call(QStringLiteral("GetStatus"), {}, [this](bool ok, const QString &out) {
        m_busy = false;
        if (!ok)
            return;
        m_status = parse(out);
        Q_EMIT statusChanged();
        // kettle-powerd restarted, or another applet was removed
        if (m_status.value(QStringLiteral("active_game")).toString() != desktop)
            call(QStringLiteral("SetActiveGame"), {desktop});
    });
}

void PowerBackend::connectDaemon()
{
    m_busy = true;
    call(QStringLiteral("GetInfo"), {}, [this](bool ok, const QString &out) {
        m_busy = false;
        if (!ok)
            return;
        m_info = parse(out);
        Q_EMIT infoChanged();
        const KConfigGroup values = desktopValues();
        for (const auto &p : steamProperties) {
            if (p.desktop && values.hasKey(p.key))
                setSteamProperty(QLatin1String(p.key), values.readEntry(p.key, QString()));
        }
        call(QStringLiteral("SetActiveGame"), {desktop});
        m_connected = true;
        readGame();
        tick(); // kettle-powerd answers in order: the status has the values just set
    });
}

void PowerBackend::readGame()
{
    call(QStringLiteral("GetGame"), {desktop}, [this](bool ok, const QString &out) {
        if (!ok)
            return;
        const QVariantMap game = parse(out);
        m_settings = game.value(QStringLiteral("settings")).toMap();
        m_custom = game.value(QStringLiteral("custom")).toBool();
        Q_EMIT settingsChanged();
    });
}

void PowerBackend::setSteamProperty(const QString &key, const QVariant &value)
{
    const SteamProperty *p = steamProperty(key);
    if (!p)
        return;
    QVariant v;
    switch (p->type) {
    case 's':
        v = value.toString();
        break;
    case 'u':
        v = value.toUInt();
        break;
    default:
        v = value.toInt();
    }
    QDBusMessage msg = QDBusMessage::createMethodCall(service, path, QStringLiteral("org.freedesktop.DBus.Properties"), QStringLiteral("Set"));
    msg.setArguments({QVariant(QStringLiteral("com.steampowered.SteamOSManager1.") + QLatin1String(p->iface)),
                      QVariant(QLatin1String(p->name)), QVariant::fromValue(QDBusVariant(v))});
    callMessage(msg, {});
}

void PowerBackend::setSteam(const QString &key, const QVariant &value)
{
    const SteamProperty *p = steamProperty(key);
    if (!p)
        return;
    setSteamProperty(key, value);
    if (p->desktop) {
        KConfigGroup values = desktopValues();
        values.writeEntry(p->key, value.toString());
        values.sync();
    }
    // shown at once; the next status read has kettle-powerd's own value
    QVariantMap steam = m_status.value(QStringLiteral("steam")).toMap();
    steam.insert(key, value);
    m_status.insert(QStringLiteral("steam"), steam);
    Q_EMIT statusChanged();
}

void PowerBackend::setSettings(const QVariantMap &settings)
{
    m_settings = settings;
    m_custom = true;
    Q_EMIT settingsChanged();
    call(QStringLiteral("SetGame"), {desktop, QString::fromUtf8(QJsonDocument(QJsonObject::fromVariantMap(settings)).toJson(QJsonDocument::Compact))},
         [this](bool, const QString &) { readGame(); });
}

void PowerBackend::resetSettings()
{
    call(QStringLiteral("SetGame"), {desktop, QStringLiteral("null")}, [this](bool, const QString &) { readGame(); });
}
