// SPDX-License-Identifier: BSD-3-Clause
// Performance: power, clocks, temperatures and the game's frame rate, with the power settings
// next to them. Made for the Thor's bottom screen in Game Mode (bottom-shell starts it there,
// KETTLE_BOTTOM_SHELL=1), where it follows the running game; elsewhere it's the Power applet's
// controls in a window, for Desktop Mode.
#include <QApplication>
#include <QCommandLineParser>
#include <QIcon>
#include <QQmlApplicationEngine>

int main(int argc, char *argv[])
{
    // Wayland whenever there's a Wayland display, as Plasma's own apps choose it: the bottom
    // shell's apps inherit Game Mode's XDG_SESSION_TYPE=x11, with which Qt would take KWin's
    // Xwayland instead, where the shell's 2x scale doesn't apply
    if (qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM") && !qEnvironmentVariableIsEmpty("WAYLAND_DISPLAY"))
        qputenv("QT_QPA_PLATFORM", "wayland");

    QApplication app(argc, argv);
    app.setApplicationName(QStringLiteral("kettle-performance"));
    app.setOrganizationName(QStringLiteral("kettle"));
    app.setApplicationDisplayName(QStringLiteral("Performance"));
    app.setDesktopFileName(QStringLiteral("org.kettlelinux.Performance"));
    app.setWindowIcon(QIcon::fromTheme(QStringLiteral("speedometer")));

    QCommandLineParser parser;
    parser.addHelpOption();
    const QCommandLineOption gameMode(QStringLiteral("game-mode"), QStringLiteral("Next to Steam: follow the running game"));
    parser.addOption(gameMode);
    parser.process(app);

    QQmlApplicationEngine engine;
    engine.setInitialProperties({{QStringLiteral("gameMode"),
                                  parser.isSet(gameMode) || qEnvironmentVariable("KETTLE_BOTTOM_SHELL") == QLatin1String("1")}});
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed, &app, [] { QCoreApplication::exit(1); }, Qt::QueuedConnection);
    engine.loadFromModule("org.kettle.performance", "Main");
    return app.exec();
}
