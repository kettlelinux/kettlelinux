// SPDX-License-Identifier: BSD-3-Clause
#include "backend.h"

#include <QDir>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkInterface>
#include <QProcess>
#include <QQuickWindow>

#include <memory>

#include <KConfigGroup>
#include <KIO/ApplicationLauncherJob>
#include <KService>
#include <KSharedConfig>

namespace
{
const QString helper = QStringLiteral(KETTLE_LIBDIR "/welcome-flatpak");
const QString protonHelper = QStringLiteral(KETTLE_LIBDIR "/welcome-proton");
const QString battlenetHelper = QStringLiteral(KETTLE_LIBDIR "/welcome-battlenet");
const QString steamosctl = QStringLiteral("steamosctl");
const QString androidGamesHelper = QStringLiteral("/usr/bin/kettle-android-games");

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
    m_protonPoll.setInterval(1000);
    connect(&m_protonPoll, &QTimer::timeout, this, &Backend::pollProton);
    refreshProtonInstalled();
    pollProton();
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

void Backend::installProton(const QString &tool)
{
    if (m_protonStatus.startsWith(QLatin1String("running")))
        return;
    setProtonStatus(QStringLiteral("running %1 download 0 0").arg(tool));
    runProtonHelper({QStringLiteral("start"), tool}, [this, tool](int code, const QString &, const QString &err) {
        if (code != 0) {
            setProtonStatus(QStringLiteral("error %1 ").arg(tool) + (err.isEmpty() ? QStringLiteral("Could not start the installation.") : err));
            return;
        }
        m_protonPoll.start();
    });
}

void Backend::removeProton(const QString &name)
{
    runProtonHelper({QStringLiteral("remove"), name}, [this](int, const QString &, const QString &) {
        refreshProtonInstalled();
    });
}

void Backend::refreshProton()
{
    refreshProtonInstalled();
    runProtonHelper({QStringLiteral("latest")}, [this](int, const QString &out, const QString &) {
        QVariantMap latest;
        const QStringList lines = out.split(QLatin1Char('\n'), Qt::SkipEmptyParts);
        for (const QString &line : lines) {
            const QStringList parts = line.split(QLatin1Char(' '));
            if (parts.size() == 2)
                latest.insert(parts[0], parts[1]);
        }
        m_protonLatest = latest;
        Q_EMIT protonLatestChanged();
    });
}

void Backend::refreshProtonInstalled()
{
    runProtonHelper({QStringLiteral("installed")}, [this](int, const QString &out, const QString &) {
        const QStringList builds = out.split(QLatin1Char('\n'), Qt::SkipEmptyParts);
        if (builds != m_protonInstalled) {
            m_protonInstalled = builds;
            Q_EMIT protonInstalledChanged();
        }
    });
}

void Backend::pollProton()
{
    runProtonHelper({QStringLiteral("status")}, [this](int, const QString &out, const QString &) {
        setProtonStatus(out.isEmpty() ? QStringLiteral("idle") : out);
        if (m_protonStatus.startsWith(QLatin1String("running"))) {
            m_protonPoll.start();
        } else {
            m_protonPoll.stop();
            refreshProtonInstalled();
        }
    });
}

void Backend::setProtonStatus(const QString &status)
{
    if (status == m_protonStatus)
        return;
    m_protonStatus = status;
    Q_EMIT protonStatusChanged();
}

void Backend::installBattlenet()
{
    if (m_battlenetBusy)
        return;
    m_battlenetBusy = true;
    m_battlenetError.clear();
    Q_EMIT battlenetChanged();
    run(battlenetHelper, {QStringLiteral("install")}, [this](int code, const QString &, const QString &err) {
        m_battlenetBusy = false;
        if (code != 0)
            m_battlenetError = err.isEmpty() ? QStringLiteral("Battle.net could not be installed.") : err;
        Q_EMIT battlenetChanged();
        refreshBattlenet();
    });
}

void Backend::refreshBattlenet()
{
    run(battlenetHelper, {QStringLiteral("status")}, [this](int, const QString &out, const QString &) {
        const QVariantMap status = QJsonDocument::fromJson(out.toUtf8()).object().toVariantMap();
        if (status != m_battlenet) {
            m_battlenet = status;
            Q_EMIT battlenetChanged();
        }
    });
}

void Backend::runProtonHelper(const QStringList &args, std::function<void(int, const QString &, const QString &)> done)
{
    run(protonHelper, args, std::move(done));
}

void Backend::runHelper(const QStringList &args, std::function<void(int, const QString &, const QString &)> done)
{
    run(helper, args, std::move(done));
}

void Backend::run(const QString &program, const QStringList &args, std::function<void(int, const QString &, const QString &)> done,
                  std::function<void(const QByteArray &)> stderrLine)
{
    auto *p = new QProcess(this);
    // with stderrLine, stderr is read as it comes; what's left of it goes to done
    auto err = std::make_shared<QByteArray>();
    if (stderrLine) {
        connect(p, &QProcess::readyReadStandardError, this, [p, err, stderrLine] {
            err->append(p->readAllStandardError());
            qsizetype nl;
            while ((nl = err->indexOf('\n')) >= 0) {
                stderrLine(err->left(nl));
                err->remove(0, nl + 1);
            }
        });
    }
    connect(p, &QProcess::finished, this, [p, err, done](int code, QProcess::ExitStatus status) {
        err->append(p->readAllStandardError());
        done(status == QProcess::NormalExit ? code : -1,
             QString::fromUtf8(p->readAllStandardOutput()).trimmed(),
             QString::fromUtf8(*err).trimmed());
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

bool Backend::hasAndroidGames() const
{
    return QFileInfo(androidGamesHelper).isExecutable();
}

void Backend::androidGames(const QString &command, const QString &arg)
{
    if (m_androidBusy)
        return;
    m_androidBusy = true;
    Q_EMIT androidBusyChanged();
    m_androidDownloaded = m_androidDownloadTotal = 0;
    Q_EMIT androidProgressChanged();
    // downloads report "PROGRESS <bytes> <total bytes>" lines on stderr
    auto progress = [this](const QByteArray &line) {
        const QList<QByteArray> parts = line.trimmed().split(' ');
        if (parts.size() == 3 && parts[0] == "PROGRESS") {
            m_androidDownloaded = parts[1].toDouble();
            m_androidDownloadTotal = parts[2].toDouble();
            Q_EMIT androidProgressChanged();
        }
    };
    run(androidGamesHelper, {command, arg}, [this, command](int, const QString &out, const QString &err) {
        QVariantMap result = QJsonDocument::fromJson(out.toUtf8()).object().toVariantMap();
        if (result.isEmpty()) {
            result.insert(QStringLiteral("ok"), false);
            result.insert(QStringLiteral("error"), err.isEmpty() ? QStringLiteral("kettle-android-games failed.") : err);
        }
        m_androidBusy = false;
        m_androidDownloaded = m_androidDownloadTotal = 0;
        Q_EMIT androidProgressChanged();
        Q_EMIT androidBusyChanged();
        Q_EMIT androidResult(command, result);
    }, progress);
}

bool Backend::saveScreenshot(QQuickWindow *window, const QString &name)
{
    if (m_screenshotDir.isEmpty() || !window)
        return false;
    return window->grabWindow().save(QDir(m_screenshotDir).filePath(name + QStringLiteral(".png")));
}
