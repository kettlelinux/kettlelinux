// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include <QList>
#include <QObject>
#include <QStringList>
#include <QTimer>
#include <QVariant>
#include <qqmlregistration.h>

// Readings kettle-powerd doesn't give, straight from the kernel: CPU load, temperatures by
// part, memory and the battery's stored energy. Temperatures are the hottest of the thermal
// zones named for each part (Qualcomm's cpu*/cpuss* and gpu* zones) and the battery's own.
// A reading the device doesn't have is undefined.
class SystemStats : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    // all CPUs' load, and the busiest one's, 0..1, since the last reading
    Q_PROPERTY(QVariant cpuLoad READ cpuLoad NOTIFY changed)
    Q_PROPERTY(QVariant cpuBusiest READ cpuBusiest NOTIFY changed)
    // °C
    Q_PROPERTY(QVariant cpuTemp READ cpuTemp NOTIFY changed)
    Q_PROPERTY(QVariant gpuTemp READ gpuTemp NOTIFY changed)
    Q_PROPERTY(QVariant batteryTemp READ batteryTemp NOTIFY changed)
    // bytes
    Q_PROPERTY(double memTotal READ memTotal NOTIFY changed)
    Q_PROPERTY(double memUsed READ memUsed NOTIFY changed)
    Q_PROPERTY(double swapTotal READ swapTotal NOTIFY changed)
    Q_PROPERTY(double swapUsed READ swapUsed NOTIFY changed)
    // Wh in the battery now, and when full
    Q_PROPERTY(QVariant batteryEnergy READ batteryEnergy NOTIFY changed)
    Q_PROPERTY(QVariant batteryEnergyFull READ batteryEnergyFull NOTIFY changed)
    // how often it's read, ms
    Q_PROPERTY(int interval READ interval WRITE setInterval NOTIFY intervalChanged)

public:
    explicit SystemStats(QObject *parent = nullptr);

    QVariant cpuLoad() const { return m_cpuLoad; }
    QVariant cpuBusiest() const { return m_cpuBusiest; }
    QVariant cpuTemp() const { return m_cpuTemp; }
    QVariant gpuTemp() const { return m_gpuTemp; }
    QVariant batteryTemp() const { return m_batteryTemp; }
    double memTotal() const { return m_memTotal; }
    double memUsed() const { return m_memUsed; }
    double swapTotal() const { return m_swapTotal; }
    double swapUsed() const { return m_swapUsed; }
    QVariant batteryEnergy() const { return m_batteryEnergy; }
    QVariant batteryEnergyFull() const { return m_batteryEnergyFull; }
    int interval() const { return m_timer.interval(); }
    void setInterval(int ms);

Q_SIGNALS:
    void changed();
    void intervalChanged();

private:
    void poll();
    void readCpu();
    void readMemory();
    void readBattery();

    QTimer m_timer;
    QStringList m_cpuZones;
    QStringList m_gpuZones;
    QString m_battery; // /sys/class/power_supply/<the battery>/
    QHash<QByteArray, QPair<quint64, quint64>> m_stat; // cpuN -> (total, idle) at the last reading
    QVariant m_cpuLoad;
    QVariant m_cpuBusiest;
    QVariant m_cpuTemp;
    QVariant m_gpuTemp;
    QVariant m_batteryTemp;
    double m_memTotal = 0;
    double m_memUsed = 0;
    double m_swapTotal = 0;
    double m_swapUsed = 0;
    QVariant m_batteryEnergy;
    QVariant m_batteryEnergyFull;
};
