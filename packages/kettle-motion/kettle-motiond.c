// SPDX-License-Identifier: GPL-3.0-or-later
//
// kettle-motiond: the motion sensors of Kettle's Qualcomm handhelds as an evdev device.
//
// On the SM8550 handhelds the accelerometer and gyroscope hang off the ADSP's sensor island,
// which only the Qualcomm Sensor Core on the ADSP can read (hexagonrpcd starts it). This
// streams both sensors through libssc into a uinput motion-sensor device, "Kettle Motion
// Sensors", in the kernel's motion-sensor layout: INPUT_PROP_ACCELEROMETER, ABS_X/Y/Z
// acceleration and ABS_RX/RY/RZ angular velocity, X right, Y toward the top edge, Z out of
// the screen, scaled like the Steam Deck's (16384 per g, 16 per degree/s). InputPlumber reads
// it into the virtual Steam Deck controller's motion.
//
// The sensors only stream when they're wanted, to save power: by default while a game runs
// (the Gyro Decky plugin reports games starting and stopping), or always, or never. Never
// while the system sleeps: a logind delay lock gives time to stop them first. The setting
// and the state are on the system bus, org.kettlelinux.Motion1:
//   Get() -> a{sv}         available, mode, game, streaming, rate, gyro (degree/s, now)
//   SetMode(s)             "games", "always" or "off" (kept in /var/lib/kettle-motion)
//   SetGame(b)             whether a game is running
//
// Usage: kettle-motiond [--rate HZ] [--accel-rate HZ] [--matrix x1,x2,x3,y1,y2,y3,z1,z2,z3]
//   --rate        sample rate requested from the gyroscope (default 400)
//   --accel-rate  and from the accelerometer (default 100): it only gives Steam the direction
//                 of gravity, which InputPlumber holds between its reports
//   --matrix  rotates the Sensor Core's axes into the layout above (default: the device's
//             entry in /usr/share/kettle-motion/devices.conf, else identity)

#include <errno.h>
#include <fcntl.h>
#include <linux/uinput.h>
#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include <gio/gio.h>
#include <gio/gunixfdlist.h>
#include <glib-unix.h>
#include <glib.h>
#include <libssc/libssc-sensor.h>
#include <libssc/libssc-sensor-accelerometer.h>
#include <libssc/libssc-sensor-gyroscope.h>

#define DEVICE_NAME "Kettle Motion Sensors"
#define BUS_NAME "org.kettlelinux.Motion1"
#define OBJ_PATH "/org/kettlelinux/Motion1"
#define SETTINGS "/var/lib/kettle-motion/settings.ini"
#define DEVICES "/usr/share/kettle-motion/devices.conf"
#define ACCEL_RES_PER_G 16384
#define GYRO_RES_PER_DPS 16
#define ACCEL_RANGE_G 16
#define GYRO_RANGE_DPS 2000
#define STANDARD_GRAVITY 9.80665
// The gyro's first samples after it starts read its full scale (2000 degree/s) on every axis
#define GYRO_STARTUP_RADS 34.9
// Finding or starting the sensors again after a failure: this long, doubled each time, up to MAX
#define SENSOR_RETRY_SECONDS 3
#define SENSOR_RETRY_MAX_SECONDS 60

static const gchar introspection_xml[] =
	"<node>"
	"  <interface name='" BUS_NAME "'>"
	"    <method name='Get'><arg name='state' type='a{sv}' direction='out'/></method>"
	"    <method name='SetMode'><arg name='mode' type='s' direction='in'/></method>"
	"    <method name='SetGame'><arg name='running' type='b' direction='in'/></method>"
	"  </interface>"
	"</node>";

static GMainLoop *loop;
static GDBusConnection *system_bus;
static double matrix[3][3] = { { 1, 0, 0 }, { 0, 1, 0 }, { 0, 0, 1 } };
static gdouble rate = 400;
static gdouble accel_rate = 100;
static int exit_status;

static SSCSensorAccelerometer *accel;
static SSCSensorGyroscope *gyro;
static int uinput_fd = -1;
static gboolean available;	// both sensors found and the uinput device made
static gboolean streaming;
static gboolean gyro_settled;
static double gyro_dps;		// the latest angular speed, for the plugin's meter

static gchar *mode;		// "games", "always" or "off"
static gboolean game_running;
static gboolean sleeping;
static int sleep_lock = -1;
static guint start_retry;	// a timeout to try starting the sensors again
static guint start_backoff;	// its seconds, 0 after a start that worked
static guint find_backoff;	// the same for finding them

// One sample: the timestamp, three axes and the report, in one write()
static void report(__u16 code, gfloat x, gfloat y, gfloat z, double scale)
{
	double in[3] = { x, y, z };
	struct input_event ev[5] = {
		{ .type = EV_MSC, .code = MSC_TIMESTAMP, .value = (__s32)(g_get_monotonic_time() & 0x7fffffff) },
		[4] = { .type = EV_SYN, .code = SYN_REPORT },
	};

	for (int i = 0; i < 3; i++) {
		double v = matrix[i][0] * in[0] + matrix[i][1] * in[1] + matrix[i][2] * in[2];

		ev[1 + i] = (struct input_event){ .type = EV_ABS, .code = code + i, .value = (__s32)lround(v * scale) };
	}
	if (write(uinput_fd, ev, sizeof(ev)) != sizeof(ev))
		g_warning("uinput write failed: %s", g_strerror(errno));
}

// m/s²
static void accel_measurement(SSCSensorAccelerometer *sensor, gfloat x, gfloat y, gfloat z, gpointer data)
{
	report(ABS_X, x, y, z, ACCEL_RES_PER_G / STANDARD_GRAVITY);
}

// rad/s
static void gyro_measurement(SSCSensorGyroscope *sensor, gfloat x, gfloat y, gfloat z, gpointer data)
{
	if (!gyro_settled) {
		if (fabsf(x) > GYRO_STARTUP_RADS && fabsf(y) > GYRO_STARTUP_RADS && fabsf(z) > GYRO_STARTUP_RADS)
			return;
		gyro_settled = TRUE;
	}
	gyro_dps = sqrt(x * x + y * y + z * z) * 180.0 / G_PI;
	report(ABS_RX, x, y, z, GYRO_RES_PER_DPS * 180.0 / G_PI);
}

static int uinput_create(void)
{
	struct uinput_setup setup = { 0 };
	struct uinput_abs_setup abs = { 0 };
	int fd;

	fd = open("/dev/uinput", O_WRONLY | O_CLOEXEC);
	if (fd < 0)
		return -1;
	ioctl(fd, UI_SET_EVBIT, EV_ABS);
	ioctl(fd, UI_SET_EVBIT, EV_MSC);
	ioctl(fd, UI_SET_MSCBIT, MSC_TIMESTAMP);
	ioctl(fd, UI_SET_PROPBIT, INPUT_PROP_ACCELEROMETER);
	for (int code = ABS_X; code <= ABS_RZ; code++) {
		int is_gyro = code >= ABS_RX;
		int max = is_gyro ? GYRO_RANGE_DPS * GYRO_RES_PER_DPS : ACCEL_RANGE_G * ACCEL_RES_PER_G;

		ioctl(fd, UI_SET_ABSBIT, code);
		abs.code = code;
		abs.absinfo.minimum = -max;
		abs.absinfo.maximum = max;
		abs.absinfo.resolution = is_gyro ? GYRO_RES_PER_DPS : ACCEL_RES_PER_G;
		if (ioctl(fd, UI_ABS_SETUP, &abs) < 0)
			goto err;
	}
	snprintf(setup.name, sizeof(setup.name), DEVICE_NAME);
	setup.id.bustype = BUS_VIRTUAL;
	if (ioctl(fd, UI_DEV_SETUP, &setup) < 0 || ioctl(fd, UI_DEV_CREATE) < 0)
		goto err;
	return fd;
err:
	close(fd);
	return -1;
}

/* Streaming ********************************************************************************/

static void update_streaming(void);

static gboolean start_retry_cb(gpointer data)
{
	start_retry = 0;
	update_streaming();
	return G_SOURCE_REMOVE;
}

static guint backoff_next(guint s)
{
	return s ? MIN(s * 2, SENSOR_RETRY_MAX_SECONDS) : SENSOR_RETRY_SECONDS;
}

static void sensors_start(void)
{
	g_autoptr(GError) err = NULL;

	gyro_settled = FALSE;
	if (!ssc_sensor_accelerometer_open_sync(accel, NULL, &err) ||
	    !ssc_sensor_gyroscope_open_sync(gyro, NULL, &err)) {
		start_backoff = backoff_next(start_backoff);
		g_printerr("Can't start the sensors (trying again in %u s): %s\n", start_backoff, err->message);
		ssc_sensor_accelerometer_close_sync(accel, NULL, NULL);
		start_retry = g_timeout_add_seconds(start_backoff, start_retry_cb, NULL);
		return;
	}
	start_backoff = 0;
	streaming = TRUE;
	g_print("Streaming: gyroscope at %.0f Hz, accelerometer at %.0f Hz\n", rate, accel_rate);
}

static void sensors_stop(void)
{
	ssc_sensor_gyroscope_close_sync(gyro, NULL, NULL);
	ssc_sensor_accelerometer_close_sync(accel, NULL, NULL);
	streaming = FALSE;
	gyro_dps = 0;
	g_print("Stopped\n");
}

// Start or stop the sensors to match the mode, the game and sleep
static void update_streaming(void)
{
	gboolean want = available && !sleeping &&
			(g_str_equal(mode, "always") || (g_str_equal(mode, "games") && game_running));

	if (!want && start_retry) {
		g_source_remove(start_retry);
		start_retry = 0;
		start_backoff = 0;
	}
	if (want && !streaming && !start_retry)
		sensors_start();
	else if (!want && streaming)
		sensors_stop();
}

/* Finding the sensors: the Sensor Core comes up a moment after hexagonrpcd ******************/

static gboolean find_sensors(gpointer data);

static void sensors_found(void)
{
	uinput_fd = uinput_create();
	if (uinput_fd < 0) {
		g_printerr("Can't create the uinput device: %s\n", g_strerror(errno));
		exit_status = 1;
		g_main_loop_quit(loop);
		return;
	}
	find_backoff = 0;
	g_object_set(accel, SSC_SENSOR_SAMPLE_RATE, (gfloat)accel_rate, NULL);
	g_object_set(gyro, SSC_SENSOR_SAMPLE_RATE, (gfloat)rate, NULL);
	g_signal_connect(accel, "measurement", G_CALLBACK(accel_measurement), NULL);
	g_signal_connect(gyro, "measurement", G_CALLBACK(gyro_measurement), NULL);
	available = TRUE;
	g_print("Found the accelerometer and gyroscope; \"%s\" is ready\n", DEVICE_NAME);
	update_streaming();
}

// Not found: looked for again later and later, said the first time and once the wait is at its
// longest (the Sensor Core may never come up: no sensor files to copy, say)
static void find_again(const char *what, const char *why)
{
	guint before = find_backoff;

	find_backoff = backoff_next(find_backoff);
	if (!before)
		g_printerr("No %s yet: %s\n", what, why);
	else if (find_backoff == SENSOR_RETRY_MAX_SECONDS && before != find_backoff)
		g_printerr("Still no %s (%s): looking every %u s\n", what, why, find_backoff);
	g_timeout_add_seconds(find_backoff, find_sensors, NULL);
}

static void gyro_new_done(GObject *source, GAsyncResult *res, gpointer data)
{
	g_autoptr(GError) err = NULL;

	gyro = ssc_sensor_gyroscope_new_finish(res, &err);
	if (!gyro) {
		g_clear_object(&accel);
		find_again("gyroscope", err->message);
		return;
	}
	sensors_found();
}

static void accel_new_done(GObject *source, GAsyncResult *res, gpointer data)
{
	g_autoptr(GError) err = NULL;

	accel = ssc_sensor_accelerometer_new_finish(res, &err);
	if (!accel) {
		find_again("accelerometer", err->message);
		return;
	}
	ssc_sensor_gyroscope_new(NULL, gyro_new_done, NULL);
}

static gboolean find_sensors(gpointer data)
{
	ssc_sensor_accelerometer_new(NULL, accel_new_done, NULL);
	return G_SOURCE_REMOVE;
}

/* Sleep ************************************************************************************/

// A logind delay lock: sleep waits (up to InhibitDelayMaxSec) until it is released
static void sleep_lock_take(void)
{
	g_autoptr(GError) err = NULL;
	g_autoptr(GUnixFDList) fds = NULL;
	g_autoptr(GVariant) ret = NULL;

	if (sleep_lock >= 0)
		return;
	ret = g_dbus_connection_call_with_unix_fd_list_sync(system_bus, "org.freedesktop.login1",
		"/org/freedesktop/login1", "org.freedesktop.login1.Manager", "Inhibit",
		g_variant_new("(ssss)", "sleep", "kettle-motiond", "Stop the motion sensors", "delay"),
		G_VARIANT_TYPE("(h)"), G_DBUS_CALL_FLAGS_NONE, -1, NULL, &fds, NULL, &err);
	if (!ret) {
		g_warning("No sleep delay lock: %s", err->message);
		return;
	}
	sleep_lock = g_unix_fd_list_get(fds, 0, NULL);
}

static void on_prepare_for_sleep(GDBusConnection *conn, const gchar *sender, const gchar *path,
				 const gchar *iface, const gchar *signal, GVariant *params, gpointer data)
{
	g_variant_get(params, "(b)", &sleeping);
	update_streaming();
	if (sleeping && sleep_lock >= 0) {
		close(sleep_lock);
		sleep_lock = -1;
	} else if (!sleeping) {
		sleep_lock_take();
	}
}

/* Settings and the bus *********************************************************************/

static gboolean valid_mode(const gchar *m)
{
	return g_str_equal(m, "games") || g_str_equal(m, "always") || g_str_equal(m, "off");
}

static void settings_load(void)
{
	g_autoptr(GKeyFile) kf = g_key_file_new();
	g_autofree gchar *m = NULL;

	if (g_key_file_load_from_file(kf, SETTINGS, G_KEY_FILE_NONE, NULL))
		m = g_key_file_get_string(kf, "motion", "mode", NULL);
	mode = g_strdup(m && valid_mode(m) ? m : "games");
}

static void settings_save(void)
{
	g_autoptr(GKeyFile) kf = g_key_file_new();
	g_autoptr(GError) err = NULL;

	g_key_file_set_string(kf, "motion", "mode", mode);
	if (!g_key_file_save_to_file(kf, SETTINGS, &err))
		g_warning("Can't save the settings: %s", err->message);
}

static void on_method_call(GDBusConnection *conn, const gchar *sender, const gchar *path,
			   const gchar *iface, const gchar *method, GVariant *params,
			   GDBusMethodInvocation *inv, gpointer data)
{
	if (g_str_equal(method, "Get")) {
		GVariantBuilder b;

		g_variant_builder_init(&b, G_VARIANT_TYPE("a{sv}"));
		g_variant_builder_add(&b, "{sv}", "available", g_variant_new_boolean(available));
		g_variant_builder_add(&b, "{sv}", "mode", g_variant_new_string(mode));
		g_variant_builder_add(&b, "{sv}", "game", g_variant_new_boolean(game_running));
		g_variant_builder_add(&b, "{sv}", "streaming", g_variant_new_boolean(streaming));
		g_variant_builder_add(&b, "{sv}", "rate", g_variant_new_double(rate));
		g_variant_builder_add(&b, "{sv}", "gyro", g_variant_new_double(gyro_dps));
		g_dbus_method_invocation_return_value(inv, g_variant_new("(a{sv})", &b));
	} else if (g_str_equal(method, "SetMode")) {
		const gchar *m;

		g_variant_get(params, "(&s)", &m);
		if (!valid_mode(m)) {
			g_dbus_method_invocation_return_error(inv, G_DBUS_ERROR, G_DBUS_ERROR_INVALID_ARGS,
							      "mode is games, always or off");
			return;
		}
		if (!g_str_equal(m, mode)) {
			g_free(mode);
			mode = g_strdup(m);
			settings_save();
			g_print("Mode: %s\n", mode);
			update_streaming();
		}
		g_dbus_method_invocation_return_value(inv, NULL);
	} else if (g_str_equal(method, "SetGame")) {
		gboolean running;

		g_variant_get(params, "(b)", &running);
		if (running != game_running) {
			game_running = running;
			g_print("Game %s\n", running ? "started" : "stopped");
			update_streaming();
		}
		g_dbus_method_invocation_return_value(inv, NULL);
	}
}

static const GDBusInterfaceVTable vtable = { on_method_call, NULL, NULL, { 0 } };

static void on_name_lost(GDBusConnection *conn, const gchar *name, gpointer data)
{
	g_printerr("Lost or couldn't own %s\n", name);
	exit_status = 1;
	g_main_loop_quit(loop);
}

static gboolean matrix_parse(const gchar *str)
{
	g_auto(GStrv) v = g_strsplit(str, ",", -1);

	if (g_strv_length(v) != 9)
		return FALSE;
	for (int i = 0; i < 9; i++)
		matrix[i / 3][i % 3] = g_ascii_strtod(v[i], NULL);
	return TRUE;
}

// The rotation for this device: the first of its compatible strings with a group in DEVICES
static void matrix_for_device(void)
{
	g_autoptr(GKeyFile) kf = g_key_file_new();
	g_autofree gchar *compat = NULL;
	gsize len = 0;

	if (!g_key_file_load_from_file(kf, DEVICES, G_KEY_FILE_NONE, NULL) ||
	    !g_file_get_contents("/proc/device-tree/compatible", &compat, &len, NULL))
		return;
	for (gsize i = 0; i < len; i += strlen(compat + i) + 1) {
		g_autofree gchar *m = g_key_file_get_string(kf, compat + i, "matrix", NULL);

		if (!m)
			continue;
		if (matrix_parse(m))
			g_print("Axes for %s: %s\n", compat + i, m);
		else
			g_printerr("Bad matrix for %s in %s\n", compat + i, DEVICES);
		return;
	}
}

static gboolean on_signal(gpointer data)
{
	g_main_loop_quit(loop);
	return G_SOURCE_REMOVE;
}

int main(int argc, char **argv)
{
	g_autoptr(GError) err = NULL;
	g_autoptr(GOptionContext) ctx = NULL;
	g_autoptr(GDBusNodeInfo) node = NULL;
	gchar *matrix_str = NULL;
	GOptionEntry options[] = {
		{ "rate", 0, 0, G_OPTION_ARG_DOUBLE, &rate, "Gyroscope sample rate in Hz (default 400)", "HZ" },
		{ "accel-rate", 0, 0, G_OPTION_ARG_DOUBLE, &accel_rate, "Accelerometer sample rate in Hz (default 100)", "HZ" },
		{ "matrix", 0, 0, G_OPTION_ARG_STRING, &matrix_str, "Axis rotation, 9 values by rows", "M" },
		{ NULL }
	};

	ctx = g_option_context_new("- motion sensors as an evdev device");
	g_option_context_add_main_entries(ctx, options, NULL);
	if (!g_option_context_parse(ctx, &argc, &argv, &err)) {
		g_printerr("%s\n", err->message);
		return 2;
	}
	if (!matrix_str)
		matrix_for_device();
	else if (!matrix_parse(matrix_str)) {
		g_printerr("--matrix needs 9 comma-separated values\n");
		return 2;
	}
	settings_load();
	g_print("Mode: %s\n", mode);

	loop = g_main_loop_new(NULL, FALSE);
	system_bus = g_bus_get_sync(G_BUS_TYPE_SYSTEM, NULL, &err);
	if (!system_bus) {
		g_printerr("No system bus: %s\n", err->message);
		return 1;
	}
	node = g_dbus_node_info_new_for_xml(introspection_xml, NULL);
	g_dbus_connection_register_object(system_bus, OBJ_PATH, node->interfaces[0], &vtable,
					  NULL, NULL, NULL);
	g_bus_own_name_on_connection(system_bus, BUS_NAME, G_BUS_NAME_OWNER_FLAGS_NONE,
				     NULL, on_name_lost, NULL, NULL);
	g_dbus_connection_signal_subscribe(system_bus, "org.freedesktop.login1",
		"org.freedesktop.login1.Manager", "PrepareForSleep", "/org/freedesktop/login1",
		NULL, G_DBUS_SIGNAL_FLAGS_NONE, on_prepare_for_sleep, NULL, NULL);
	sleep_lock_take();

	find_sensors(NULL);
	g_unix_signal_add(SIGTERM, on_signal, NULL);
	g_unix_signal_add(SIGINT, on_signal, NULL);
	g_main_loop_run(loop);

	if (streaming)
		sensors_stop();
	if (uinput_fd >= 0) {
		ioctl(uinput_fd, UI_DEV_DESTROY);
		close(uinput_fd);
	}
	return exit_status;
}
