// SPDX-License-Identifier: BSD-3-Clause
#include "systemstats.h"

#include <QDir>
#include <QFile>

#include <algorithm>
#include <optional>

namespace
{
QByteArray readFile(const QString &path)
{
    QFile f(path);
    return f.open(QIODevice::ReadOnly) ? f.readAll().trimmed() : QByteArray();
}

std::optional<qint64> readInt(const QString &path)
{
    bool ok = false;
    const qint64 v = readFile(path).toLongLong(&ok);
    return ok ? std::optional(v) : std::nullopt;
}

// the hottest of these zones, °C
QVariant hottest(const QStringList &zones)
{
    std::optional<double> hot;
    for (const QString &z : zones) {
        const auto milli = readInt(z + QStringLiteral("temp"));
        // a zone that's off or broken reads nonsense
        if (!milli || *milli < -40000 || *milli > 150000)
            continue;
        hot = std::max(hot.value_or(-1000.0), *milli / 1000.0);
    }
    return hot ? QVariant(*hot) : QVariant();
}
}

SystemStats::SystemStats(QObject *parent)
    : QObject(parent)
{
    const QString thermal = QStringLiteral("/sys/class/thermal/");
    const QStringList zones = QDir(thermal).entryList({QStringLiteral("thermal_zone*")}, QDir::Dirs | QDir::System);
    for (const QString &z : zones) {
        const QByteArray type = readFile(thermal + z + QStringLiteral("/type"));
        if (type.startsWith("cpu"))
            m_cpuZones.append(thermal + z + QLatin1Char('/'));
        else if (type.startsWith("gpu"))
            m_gpuZones.append(thermal + z + QLatin1Char('/'));
    }
    const QString supplies = QStringLiteral("/sys/class/power_supply/");
    for (const QString &s : QDir(supplies).entryList(QDir::Dirs | QDir::System | QDir::NoDotAndDotDot)) {
        if (readFile(supplies + s + QStringLiteral("/type")) == "Battery") {
            m_battery = supplies + s + QLatin1Char('/');
            break;
        }
    }
    m_timer.setInterval(1000);
    connect(&m_timer, &QTimer::timeout, this, &SystemStats::poll);
    m_timer.start();
    poll();
}

void SystemStats::setInterval(int ms)
{
    if (ms == m_timer.interval())
        return;
    m_timer.setInterval(ms);
    Q_EMIT intervalChanged();
}

void SystemStats::poll()
{
    readCpu();
    readMemory();
    readBattery();
    m_cpuTemp = hottest(m_cpuZones);
    m_gpuTemp = hottest(m_gpuZones);
    Q_EMIT changed();
}

void SystemStats::readCpu()
{
    QHash<QByteArray, QPair<quint64, quint64>> now;
    for (const QByteArray &line : readFile(QStringLiteral("/proc/stat")).split('\n')) {
        if (!line.startsWith("cpu"))
            continue;
        const QList<QByteArray> parts = line.simplified().split(' ');
        if (parts.size() < 6)
            continue;
        quint64 total = 0;
        for (qsizetype i = 1; i < parts.size(); ++i)
            total += parts[i].toULongLong();
        now.insert(parts[0], {total, parts[4].toULongLong() + parts[5].toULongLong()}); // idle + iowait
    }
    std::optional<double> all;
    double busiest = 0;
    for (auto it = now.cbegin(); it != now.cend(); ++it) {
        const auto prev = m_stat.find(it.key());
        if (prev == m_stat.cend() || it->first <= prev->first)
            continue;
        const double busy = 1.0 - double(it->second - prev->second) / double(it->first - prev->first);
        if (it.key() == "cpu")
            all = busy;
        else
            busiest = std::max(busiest, busy);
    }
    m_stat = now;
    m_cpuLoad = all ? QVariant(std::clamp(*all, 0.0, 1.0)) : QVariant();
    m_cpuBusiest = all ? QVariant(std::clamp(busiest, 0.0, 1.0)) : QVariant();
}

void SystemStats::readMemory()
{
    QHash<QByteArray, double> kb;
    for (const QByteArray &line : readFile(QStringLiteral("/proc/meminfo")).split('\n')) {
        const QList<QByteArray> parts = line.simplified().split(' ');
        if (parts.size() >= 2)
            kb.insert(parts[0].chopped(1), parts[1].toDouble()); // "MemTotal:" -> MemTotal
    }
    m_memTotal = kb.value("MemTotal") * 1024;
    m_memUsed = (kb.value("MemTotal") - kb.value("MemAvailable")) * 1024;
    m_swapTotal = kb.value("SwapTotal") * 1024;
    m_swapUsed = (kb.value("SwapTotal") - kb.value("SwapFree")) * 1024;
}

void SystemStats::readBattery()
{
    m_batteryTemp = m_batteryEnergy = m_batteryEnergyFull = QVariant();
    if (m_battery.isEmpty())
        return;
    if (const auto t = readInt(m_battery + QStringLiteral("temp")))
        m_batteryTemp = *t / 10.0;
    // energy in µWh, or charge in µAh at the voltage now
    const auto energy = readInt(m_battery + QStringLiteral("energy_now"));
    const auto energyFull = readInt(m_battery + QStringLiteral("energy_full"));
    if (energy && energyFull) {
        m_batteryEnergy = *energy / 1e6;
        m_batteryEnergyFull = *energyFull / 1e6;
        return;
    }
    const auto charge = readInt(m_battery + QStringLiteral("charge_now"));
    const auto chargeFull = readInt(m_battery + QStringLiteral("charge_full"));
    const auto volts = readInt(m_battery + QStringLiteral("voltage_now"));
    if (charge && chargeFull && volts) {
        m_batteryEnergy = *charge * (*volts / 1e6) / 1e6;
        m_batteryEnergyFull = *chargeFull * (*volts / 1e6) / 1e6;
    }
}
