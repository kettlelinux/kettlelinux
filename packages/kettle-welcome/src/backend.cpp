// SPDX-License-Identifier: BSD-3-Clause
#include "backend.h"

#include <QDir>
#include <QFileInfo>
#include <QNetworkInterface>
#include <QProcess>
#include <QQuickWindow>

#include <KConfigGroup>
#include <KIO/ApplicationLauncherJob>
#include <KService>
#include <KSharedConfig>

namespace
{
const QString helper = QStringLiteral(KETTLE_LIBDIR "/welcome-flatpak");
const QString steamosctl = QStringLiteral("steamosctl");

KConfigGroup settings()
{
    return KSharedConfig::openConfig(QStringLiteral("kettle-welcomerc"))->group(QStringLiteral("General"));
}
}

Backend::Backend(const QString &screenshotDir, QObject *parent)
    : QObject(parent)
    , m_screenshotDir(screenshotDir)
{
    m_poll.setInterval(1000);
    connect(&m_poll, &QTimer::timeout, this, &Backend::pollStatus);
    refreshApps();
    pollStatus(); // picks up an install started before the window was reopened
    refreshBootMode();
    refreshSsh();
}

bool Backend::showAtLogin() const
{
    return settings().readEntry("ShowAtLogin", false);
}

void Backend::setShowAtLogin(bool show)
{
    if (show == showAtLogin())
        return;
    KConfigGroup g = settings();
    g.writeEntry("ShowAtLogin", show);
    g.sync();
    Q_EMIT showAtLoginChanged();
}

bool Backend::hasApp(const QString &desktopId) const
{
    return KService::serviceByDesktopName(desktopId) != nullptr;
}

void Backend::launchApp(const QString &desktopId)
{
    const KService::Ptr service = KService::serviceByDesktopName(desktopId);
    if (!service)
        return;
    (new KIO::ApplicationLauncherJob(service))->start();
}

void Backend::openSettings(const QString &module)
{
    QProcess::startDetached(QStringLiteral("kcmshell6"), {module});
}

void Backend::openSystemSettings()
{
    launchApp(QStringLiteral("systemsettings"));
}

void Backend::returnToGameMode()
{
    // what the desktop's Return to Gaming Mode icon runs (steamdeck-kde-presets)
    QProcess::startDetached(QStringLiteral("sh"),
                            {QStringLiteral("-c"),
                             QStringLiteral("steamosctl switch-to-game-mode || qdbus org.kde.Shutdown /Shutdown org.kde.Shutdown.logout")});
}

void Backend::refreshBootMode()
{
    run(steamosctl, {QStringLiteral("get-default-login-mode")}, [this](int code, const QString &out, const QString &) {
        const QString o = out.toLower();
        const QString mode = code != 0 ? QString()
            : o.contains(QLatin1String("desktop")) ? QStringLiteral("desktop")
            : o.contains(QLatin1String("game")) ? QStringLiteral("game")
            : QString();
        if (mode != m_bootMode) {
            m_bootMode = mode;
            Q_EMIT bootModeChanged();
        }
    });
}

void Backend::setBootMode(const QString &mode)
{
    if (mode == m_bootMode || (mode != QLatin1String("game") && mode != QLatin1String("desktop")))
        return;
    m_bootMode = mode;
    Q_EMIT bootModeChanged();
    // read it back either way, so a refused change shows the mode still in effect
    run(steamosctl, {QStringLiteral("set-default-login-mode"), mode}, [this](int, const QString &, const QString &) {
        refreshBootMode();
    });
}

void Backend::refreshSsh()
{
    // enabled at boot and running now: what the switch promises
    run(QStringLiteral("systemctl"), {QStringLiteral("is-enabled"), QStringLiteral("sshd.service")}, [this](int enabled, const QString &, const QString &) {
        run(QStringLiteral("systemctl"), {QStringLiteral("is-active"), QStringLiteral("sshd.service")}, [this, enabled](int active, const QString &, const QString &) {
            m_sshEnabled = enabled == 0 && active == 0;
            m_sshBusy = false;
            Q_EMIT sshChanged();
        });
    });
}

void Backend::setSshEnabled(bool enabled)
{
    if (m_sshBusy || enabled == m_sshEnabled)
        return;
    m_sshBusy = true;
    Q_EMIT sshChanged();
    // systemd asks polkit, so the desktop's authentication dialog asks for the password;
    // read the state back either way, so a cancelled dialog leaves the switch where it was
    run(QStringLiteral("systemctl"),
        {enabled ? QStringLiteral("enable") : QStringLiteral("disable"), QStringLiteral("--now"), QStringLiteral("sshd.service")},
        [this](int, const QString &, const QString &) {
            refreshSsh();
        });
}

QStringList Backend::addresses() const
{
    QStringList out;
    const auto ifaces = QNetworkInterface::allInterfaces();
    for (const QNetworkInterface &i : ifaces) {
        if (!(i.flags() & QNetworkInterface::IsUp) || (i.flags() & QNetworkInterface::IsLoopBack))
            continue;
        const auto entries = i.addressEntries();
        for (const QNetworkAddressEntry &e : entries) {
            if (e.ip().protocol() == QAbstractSocket::IPv4Protocol)
                out << e.ip().toString();
        }
    }
    return out;
}

void Backend::installApps(const QStringList &ids)
{
    if (ids.isEmpty() || m_installStatus.startsWith(QLatin1String("running")))
        return;
    setInstallStatus(QStringLiteral("running 0 %1 %2").arg(ids.size()).arg(ids.first()));
    runHelper(QStringList{QStringLiteral("start")} + ids, [this](int code, const QString &, const QString &err) {
        if (code != 0) {
            // start refused (bad ID, an install already running): show what it said
            setInstallStatus(QStringLiteral("error - ") + (err.isEmpty() ? QStringLiteral("Could not start the installation.") : err));
            return;
        }
        m_poll.start();
    });
}

void Backend::refreshApps()
{
    runHelper({QStringLiteral("installed")}, [this](int, const QString &out, const QString &) {
        const QStringList apps = out.split(QLatin1Char('\n'), Qt::SkipEmptyParts);
        if (apps != m_installedApps) {
            m_installedApps = apps;
            Q_EMIT installedAppsChanged();
        }
    });
}

void Backend::pollStatus()
{
    runHelper({QStringLiteral("status")}, [this](int, const QString &out, const QString &) {
        setInstallStatus(out.isEmpty() ? QStringLiteral("idle") : out);
        if (m_installStatus.startsWith(QLatin1String("running"))) {
            m_poll.start();
        } else {
            m_poll.stop();
            refreshApps();
        }
    });
}

void Backend::setInstallStatus(const QString &status)
{
    if (status == m_installStatus)
        return;
    m_installStatus = status;
    Q_EMIT installStatusChanged();
}

void Backend::runHelper(const QStringList &args, std::function<void(int, const QString &, const QString &)> done)
{
    run(helper, args, std::move(done));
}

void Backend::run(const QString &program, const QStringList &args, std::function<void(int, const QString &, const QString &)> done)
{
    auto *p = new QProcess(this);
    connect(p, &QProcess::finished, this, [p, done](int code, QProcess::ExitStatus status) {
        done(status == QProcess::NormalExit ? code : -1,
             QString::fromUtf8(p->readAllStandardOutput()).trimmed(),
             QString::fromUtf8(p->readAllStandardError()).trimmed());
        p->deleteLater();
    });
    connect(p, &QProcess::errorOccurred, this, [p, program, done](QProcess::ProcessError e) {
        if (e == QProcess::FailedToStart) {
            done(-1, {}, QFileInfo(program).fileName() + QStringLiteral(" is missing"));
            p->deleteLater();
        }
    });
    p->start(program, args);
}

bool Backend::saveScreenshot(QQuickWindow *window, const QString &name)
{
    if (m_screenshotDir.isEmpty() || !window)
        return false;
    return window->grabWindow().save(QDir(m_screenshotDir).filePath(name + QStringLiteral(".png")));
}
