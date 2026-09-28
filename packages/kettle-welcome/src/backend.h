// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include <QObject>
#include <QStringList>
#include <QVariantMap>
#include <QTimer>

#include <functional>

class QQuickWindow;

// What the QML side can't do itself: start apps and settings modules, remember the "show at
// login" choice, set what the device starts up in, switch the SSH server, and run welcome-flatpak (Gaming Extras)
// without blocking the UI.
class Backend : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool showAtLogin READ showAtLogin WRITE setShowAtLogin NOTIFY showAtLoginChanged)
    Q_PROPERTY(QStringList installedApps READ installedApps NOTIFY installedAppsChanged)
    // welcome-flatpak's status line: idle | running I N ID | done N | error ID MESSAGE
    Q_PROPERTY(QString installStatus READ installStatus NOTIFY installStatusChanged)
    Q_PROPERTY(QString screenshotDir READ screenshotDir CONSTANT)
    // steamos-manager's default login mode: game | desktop, empty while unknown
    Q_PROPERTY(QString bootMode READ bootMode WRITE setBootMode NOTIFY bootModeChanged)
    // the SSH server (sshd.service) enabled and running; sshBusy while a change is pending
    Q_PROPERTY(bool sshEnabled READ sshEnabled WRITE setSshEnabled NOTIFY sshChanged)
    Q_PROPERTY(bool sshBusy READ sshBusy NOTIFY sshChanged)
    // this device's IPv4 addresses, for "ssh user@address"
    Q_PROPERTY(QStringList addresses READ addresses NOTIFY sshChanged)
    Q_PROPERTY(QString userName READ userName CONSTANT)
    // kettle-android-games (package kettle-lepton) is installed; androidBusy while it runs
    Q_PROPERTY(bool hasAndroidGames READ hasAndroidGames CONSTANT)
    Q_PROPERTY(bool androidBusy READ androidBusy NOTIFY androidBusyChanged)

public:
    explicit Backend(const QString &screenshotDir, QObject *parent = nullptr);

    bool showAtLogin() const;
    void setShowAtLogin(bool show);
    QStringList installedApps() const { return m_installedApps; }
    QString installStatus() const { return m_installStatus; }
    QString screenshotDir() const { return m_screenshotDir; }
    QString bootMode() const { return m_bootMode; }
    void setBootMode(const QString &mode);
    bool sshEnabled() const { return m_sshEnabled; }
    void setSshEnabled(bool enabled);
    bool sshBusy() const { return m_sshBusy; }
    QStringList addresses() const;
    QString userName() const { return QString::fromLocal8Bit(qgetenv("USER")); }
    bool hasAndroidGames() const;
    bool androidBusy() const { return m_androidBusy; }

    Q_INVOKABLE bool hasApp(const QString &desktopId) const;
    Q_INVOKABLE void launchApp(const QString &desktopId);
    // a System Settings module in a window of its own (kcmshell6), e.g. "kcm_users"
    Q_INVOKABLE void openSettings(const QString &module);
    Q_INVOKABLE void openSystemSettings();
    Q_INVOKABLE void returnToGameMode();

    Q_INVOKABLE void installApps(const QStringList &ids);
    Q_INVOKABLE void refreshApps();

    Q_INVOKABLE bool saveScreenshot(QQuickWindow *window, const QString &name);

    // kettle-android-games COMMAND ARG (add FILE, fdroid-search TEXT, fdroid-add PACKAGE); its
    // JSON result arrives in androidResult. One command at a time.
    Q_INVOKABLE void androidGames(const QString &command, const QString &arg);

Q_SIGNALS:
    void showAtLoginChanged();
    void installedAppsChanged();
    void installStatusChanged();
    void bootModeChanged();
    void sshChanged();
    // a second start (menu entry, Gaming Extras entry) asks the open window to show a page
    void pageRequested(const QString &page);
    void androidBusyChanged();
    void androidResult(const QString &command, const QVariantMap &result);

private:
    void run(const QString &program, const QStringList &args, std::function<void(int, const QString &, const QString &)> done);
    void runHelper(const QStringList &args, std::function<void(int, const QString &, const QString &)> done);
    void refreshBootMode();
    void refreshSsh();
    void pollStatus();
    void setInstallStatus(const QString &status);

    QString m_screenshotDir;
    QStringList m_installedApps;
    QString m_installStatus = QStringLiteral("idle");
    QString m_bootMode;
    bool m_sshEnabled = false;
    bool m_sshBusy = false;
    bool m_androidBusy = false;
    QTimer m_poll;
};
