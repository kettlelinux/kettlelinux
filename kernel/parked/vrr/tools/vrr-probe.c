// SPDX-License-Identifier: GPL-2.0
// Based on PortareOS's vrr-probe (Copyright (C) 2026-present PortareOS,
// https://github.com/portare-ch/portareos), adapted for Kettle: any
// connector by name, any panel size, rates relative to the panel's mode, and
// frame statistics per phase from the kernel's flip timestamps.
//
// Static phases 0-6 set modes with the mode's pixel clock and a longer
// vertical front porch (100% down to 50% of the mode's rate) through ordinary
// mode setting, and flip as fast as the panel takes it: does the panel follow
// a stretched blank at all?
//
// Dynamic phases 7-13 keep the mode and commit frames on a schedule inside
// the VRR range (min..max of the mode): with VRR_ENABLED set and the
// kernel's AVR working, frames should start on the schedule, not the grid.
//
// "idle" commits once and then nothing for SECONDS: with AVR, the panel
// should fall to the range's floor (read the vblank counter meanwhile).
//
// The screen shows the phase in big digits, the target rate next to it,
// six dark grey patches (OLED flicker shows there first) and a moving bar.
//
// usage: vrr-probe CONNECTOR OUT.csv SECONDS static|dynamic|all|idle|reset [vrr] [MIN_HZ]
//   e.g. vrr-probe DSI-1 /tmp/v.csv 6 static

#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <drm/drm.h>
#include <drm/drm_mode.h>

struct buf { uint32_t handle, pitch, fb; uint64_t size; uint32_t *map; };
struct rec { uint64_t t; uint8_t phase; char kind; };

static volatile sig_atomic_t stop;
static int drm_fd = -1;
static uint32_t crtc_id, conn_id, crtc_index;
static int W, H;
static struct buf bufs[2];
static int cur, barx;
static struct rec *recs;
static size_t nrecs;
static const size_t maxrecs = 600000;

static void on_signal(int s) { (void)s; stop = 1; }

static uint64_t now_ns(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (uint64_t)ts.tv_sec * 1000000000ull + ts.tv_nsec;
}

static void sleep_until(uint64_t t)
{
	struct timespec ts = { (time_t)(t / 1000000000ull), (long)(t % 1000000000ull) };
	while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL) == EINTR && !stop)
		;
}

static void add(uint8_t phase, char kind, uint64_t t)
{
	if (nrecs < maxrecs)
		recs[nrecs++] = (struct rec){ t, phase, kind };
}

static int xioctl(int fd, unsigned long req, void *arg)
{
	int r;
	do r = ioctl(fd, req, arg); while (r == -1 && errno == EINTR);
	return r;
}

static int make_buf(struct buf *b)
{
	struct drm_mode_create_dumb cd = { .width = W, .height = H, .bpp = 32 };
	if (xioctl(drm_fd, DRM_IOCTL_MODE_CREATE_DUMB, &cd)) return -1;
	b->handle = cd.handle; b->pitch = cd.pitch; b->size = cd.size;
	struct drm_mode_fb_cmd fc = { .width = W, .height = H, .pitch = cd.pitch,
				      .bpp = 32, .depth = 24, .handle = cd.handle };
	if (xioctl(drm_fd, DRM_IOCTL_MODE_ADDFB, &fc)) return -1;
	b->fb = fc.fb_id;
	struct drm_mode_map_dumb md = { .handle = cd.handle };
	if (xioctl(drm_fd, DRM_IOCTL_MODE_MAP_DUMB, &md)) return -1;
	b->map = mmap(NULL, cd.size, PROT_READ | PROT_WRITE, MAP_SHARED, drm_fd, md.offset);
	return b->map == MAP_FAILED ? -1 : 0;
}

static void rect(struct buf *b, int x, int y, int w, int h, uint32_t c)
{
	for (int j = y < 0 ? 0 : y; j < y + h && j < H; j++) {
		uint32_t *row = (uint32_t *)((uint8_t *)b->map + (size_t)j * b->pitch);
		for (int i = x < 0 ? 0 : x; i < x + w && i < W; i++)
			row[i] = c;
	}
}

static void digit(struct buf *b, int x, int y, int d, uint32_t c)
{
	static const uint8_t seg[10] = { 0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f };
	const int L = 70, T = 14;
	uint8_t s = seg[d % 10];
	if (s & 0x01) rect(b, x + T, y, L, T, c);
	if (s & 0x02) rect(b, x + T + L, y + T, T, L, c);
	if (s & 0x04) rect(b, x + T + L, y + 2 * T + L, T, L, c);
	if (s & 0x08) rect(b, x + T, y + 2 * T + 2 * L, L, T, c);
	if (s & 0x10) rect(b, x, y + 2 * T + L, T, L, c);
	if (s & 0x20) rect(b, x, y + T, T, L, c);
	if (s & 0x40) rect(b, x + T, y + T + L, L, T, c);
}

static uint32_t grey(int v) { return 0xff000000u | (v << 16) | (v << 8) | v; }

static void number(struct buf *b, int x, int y, int n, uint32_t c)
{
	char s[8];
	snprintf(s, sizeof s, "%d", n);
	for (int i = 0; s[i]; i++, x += 120)
		digit(b, x, y, s[i] - '0', c);
}

static int bar_y(void) { return H - 140; }

/*
 * VRR_ALT=1: the two buffers differ everywhere (diagonal colour bands, one the
 * other's complement), so every slice of every frame changes and a frame shown
 * half-written in the panel's RAM is visible.
 */
static void paint_alt(struct buf *b, int which)
{
	for (int j = 0; j < H; j++) {
		uint32_t *row = (uint32_t *)((uint8_t *)b->map + (size_t)j * b->pitch);
		for (int i = 0; i < W; i++) {
			int v = ((i + j) / 24 + (which ? 3 : 0)) & 7;
			uint32_t c = 0xff000000u | ((v & 1) ? 0xd02020 : 0x202020) |
				     ((v & 2) ? 0x00c000 : 0) | ((v & 4) ? 0x0000e0 : 0);
			row[i] = c;
		}
	}
}

static void paint(struct buf *b, int phase, int hz)
{
	if (getenv("VRR_ALT")) {
		paint_alt(b, b == &bufs[1]);
		number(b, 40, 40, phase, grey(255));
		number(b, W / 2, 40, hz, grey(255));
		return;
	}
	static const int levels[] = { 4, 8, 16, 32, 64, 128 };
	int pw = (W - 80) / 6;
	rect(b, 0, 0, W, H, grey(40));
	number(b, 40, 40, phase, grey(255));
	number(b, W / 2, 40, hz, grey(160));
	for (int i = 0; i < 6; i++)
		rect(b, 40 + i * pw, 320, pw - 20, H / 3, grey(levels[i]));
}

static int set_mode(struct buf *b, struct drm_mode_modeinfo *m)
{
	struct drm_mode_crtc s = { 0 };
	s.crtc_id = crtc_id;
	s.fb_id = b->fb;
	s.set_connectors_ptr = (uintptr_t)&conn_id;
	s.count_connectors = 1;
	s.mode = *m;
	s.mode_valid = 1;
	return xioctl(drm_fd, DRM_IOCTL_MODE_SETCRTC, &s);
}

static double mode_hz(const struct drm_mode_modeinfo *m)
{
	return m->clock * 1000.0 / ((double)m->htotal * m->vtotal);
}

static struct drm_mode_modeinfo stretched(const struct drm_mode_modeinfo *base, int vtotal)
{
	struct drm_mode_modeinfo m = *base;
	int vsw = base->vsync_end - base->vsync_start;
	int vbp = base->vtotal - base->vsync_end;
	int vfp = vtotal - base->vdisplay - vsw - vbp;
	m.vsync_start = base->vdisplay + vfp;
	m.vsync_end = m.vsync_start + vsw;
	m.vtotal = vtotal;
	m.vrefresh = (uint32_t)(mode_hz(&m) + 0.5);
	m.type = DRM_MODE_TYPE_USERDEF;
	snprintf(m.name, sizeof m.name, "%ux%u-v%d", m.hdisplay, m.vdisplay, vtotal);
	return m;
}

static const char *conn_type_name(uint32_t t)
{
	switch (t) {
	case DRM_MODE_CONNECTOR_DSI: return "DSI";
	case DRM_MODE_CONNECTOR_DisplayPort: return "DP";
	case DRM_MODE_CONNECTOR_eDP: return "eDP";
	case DRM_MODE_CONNECTOR_HDMIA: return "HDMI-A";
	default: return "other";
	}
}

static int find_display(const char *want, struct drm_mode_modeinfo *base)
{
	struct drm_mode_card_res res = { 0 };
	if (xioctl(drm_fd, DRM_IOCTL_MODE_GETRESOURCES, &res)) return -1;
	uint32_t *crtcs = calloc(res.count_crtcs + 1, 4);
	uint32_t *conns = calloc(res.count_connectors + 1, 4);
	uint32_t *encs = calloc(res.count_encoders + 1, 4);
	uint32_t *fbs = calloc(res.count_fbs + 1, 4);
	res.crtc_id_ptr = (uintptr_t)crtcs;
	res.connector_id_ptr = (uintptr_t)conns;
	res.encoder_id_ptr = (uintptr_t)encs;
	res.fb_id_ptr = (uintptr_t)fbs;
	if (xioctl(drm_fd, DRM_IOCTL_MODE_GETRESOURCES, &res)) return -1;
	for (uint32_t i = 0; i < res.count_connectors; i++) {
		struct drm_mode_get_connector c = { .connector_id = conns[i] };
		if (xioctl(drm_fd, DRM_IOCTL_MODE_GETCONNECTOR, &c)) continue;
		char name[32];
		snprintf(name, sizeof name, "%s-%u", conn_type_name(c.connector_type), c.connector_type_id);
		if (strcmp(name, want)) continue;
		if (c.connection != 1 || !c.count_modes) { fprintf(stderr, "%s not connected\n", want); return -1; }
		struct drm_mode_modeinfo *modes = calloc(c.count_modes, sizeof *modes);
		uint32_t *encids = calloc(c.count_encoders + 1, 4);
		struct drm_mode_get_connector c2 = { .connector_id = conns[i],
			.count_modes = c.count_modes, .modes_ptr = (uintptr_t)modes,
			.count_encoders = c.count_encoders, .encoders_ptr = (uintptr_t)encids };
		if (xioctl(drm_fd, DRM_IOCTL_MODE_GETCONNECTOR, &c2)) return -1;
		*base = modes[0];
		for (uint32_t k = 0; k < c2.count_modes; k++)
			if (modes[k].type & DRM_MODE_TYPE_PREFERRED) *base = modes[k];
		/* VRR_MODE_HZ=60: the connector's mode nearest that rate instead */
		const char *want_hz = getenv("VRR_MODE_HZ");
		if (want_hz && *want_hz) {
			double hz = atof(want_hz), best = 1e9;
			for (uint32_t k = 0; k < c2.count_modes; k++) {
				double d = mode_hz(&modes[k]) - hz;
				if (d < 0) d = -d;
				if (d < best) { best = d; *base = modes[k]; }
			}
		}
		/*
		 * VRR_MODE_VFP=76: that vertical front porch, with the pixel clock
		 * scaled so the mode keeps its rate (a custom mode).
		 */
		const char *want_vfp = getenv("VRR_MODE_VFP");
		if (want_vfp && *want_vfp) {
			int vfp = atoi(want_vfp);
			int vsw = base->vsync_end - base->vsync_start;
			int vbp = base->vtotal - base->vsync_end;
			int vtotal = base->vdisplay + vfp + vsw + vbp;
			base->clock = (uint32_t)((uint64_t)base->clock * vtotal / base->vtotal);
			base->vsync_start = base->vdisplay + vfp;
			base->vsync_end = base->vsync_start + vsw;
			base->vtotal = vtotal;
			base->type = DRM_MODE_TYPE_USERDEF;
			snprintf(base->name, sizeof base->name, "%ux%u-f%d", base->hdisplay, base->vdisplay, vfp);
		}
		conn_id = conns[i];
		uint32_t enc = c2.encoder_id ? c2.encoder_id : (c2.count_encoders ? encids[0] : 0);
		struct drm_mode_get_encoder e = { .encoder_id = enc };
		if (!enc || xioctl(drm_fd, DRM_IOCTL_MODE_GETENCODER, &e)) return -1;
		if (e.crtc_id) {
			crtc_id = e.crtc_id;
			for (uint32_t k = 0; k < res.count_crtcs; k++)
				if (crtcs[k] == crtc_id) crtc_index = k;
		} else {
			/* Unused CRTC this encoder can drive. */
			for (uint32_t k = 0; k < res.count_crtcs; k++)
				if (e.possible_crtcs & (1u << k)) { crtc_id = crtcs[k]; crtc_index = k; break; }
		}
		return crtc_id ? 0 : -1;
	}
	fprintf(stderr, "no connector %s\n", want);
	return -1;
}

static uint32_t find_prop(uint32_t obj_id, uint32_t obj_type, const char *name, uint64_t *value)
{
	struct drm_mode_obj_get_properties gp = { .obj_id = obj_id, .obj_type = obj_type };
	if (xioctl(drm_fd, DRM_IOCTL_MODE_OBJ_GETPROPERTIES, &gp) || !gp.count_props)
		return 0;
	uint32_t *ids = calloc(gp.count_props, sizeof *ids);
	uint64_t *vals = calloc(gp.count_props, sizeof *vals);
	gp.props_ptr = (uintptr_t)ids;
	gp.prop_values_ptr = (uintptr_t)vals;
	uint32_t found = 0;
	if (!xioctl(drm_fd, DRM_IOCTL_MODE_OBJ_GETPROPERTIES, &gp)) {
		for (uint32_t i = 0; i < gp.count_props && !found; i++) {
			struct drm_mode_get_property pr = { .prop_id = ids[i] };
			if (!xioctl(drm_fd, DRM_IOCTL_MODE_GETPROPERTY, &pr) && !strcmp(pr.name, name)) {
				found = ids[i];
				if (value) *value = vals[i];
			}
		}
	}
	free(ids);
	free(vals);
	return found;
}

static int set_vrr(int on)
{
	uint32_t id = find_prop(crtc_id, DRM_MODE_OBJECT_CRTC, "VRR_ENABLED", NULL);
	if (!id) {
		fprintf(stderr, "the CRTC has no VRR_ENABLED\n");
		return -1;
	}
	struct drm_mode_obj_set_property sp = { .value = (uint64_t)on, .prop_id = id,
		.obj_id = crtc_id, .obj_type = DRM_MODE_OBJECT_CRTC };
	if (xioctl(drm_fd, DRM_IOCTL_MODE_OBJ_SETPROPERTY, &sp)) {
		perror("VRR_ENABLED");
		return -1;
	}
	return 0;
}

static int wait_flips(uint8_t phase, int timeout_ms)
{
	struct pollfd p = { drm_fd, POLLIN, 0 };
	if (poll(&p, 1, timeout_ms) <= 0 || !(p.revents & POLLIN))
		return 0;
	char ebuf[1024];
	uint64_t t = now_ns();
	ssize_t n = read(drm_fd, ebuf, sizeof ebuf);
	int done = 0;
	for (ssize_t off = 0; off + (ssize_t)sizeof(struct drm_event) <= n;) {
		struct drm_event *e = (struct drm_event *)(ebuf + off);
		if (e->type == DRM_EVENT_FLIP_COMPLETE) {
			struct drm_event_vblank *v = (struct drm_event_vblank *)e;
			add(phase, 'F', (uint64_t)v->tv_sec * 1000000000ull + v->tv_usec * 1000ull);
			add(phase, 'f', t);
			done++;
		}
		off += e->length;
	}
	return done;
}

static int flip(uint8_t phase)
{
	struct buf *b = &bufs[cur ^ 1];
	rect(b, 0, bar_y(), W, 60, grey(40));
	rect(b, barx, bar_y(), 24, 60, grey(255));
	barx = (barx + 8) % (W - 24);
	struct drm_mode_crtc_page_flip pf = { .crtc_id = crtc_id, .fb_id = b->fb,
		.flags = DRM_MODE_PAGE_FLIP_EVENT, .user_data = phase };
	if (xioctl(drm_fd, DRM_IOCTL_MODE_PAGE_FLIP, &pf))
		return -1;
	add(phase, 'C', now_ns());
	cur ^= 1;
	return 0;
}

static int cmp_u64(const void *a, const void *b)
{
	uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
	return x < y ? -1 : x > y;
}

/*
 * Intervals between the kernel's flip timestamps (F) and between our own
 * receive times (f) in a phase: the kernel's derive from the mode's fixed
 * frame length, so under AVR our receive times are the ones to believe.
 */
static void stats(uint8_t phase, const char *label)
{
	for (int pass = 0; pass < 2; pass++) {
		char kind = pass ? 'f' : 'F';
		uint64_t *d = malloc(nrecs * sizeof *d);
		size_t n = 0;
		uint64_t prev = 0;
		for (size_t i = 0; i < nrecs; i++) {
			if (recs[i].phase != phase || recs[i].kind != kind) continue;
			if (prev) d[n++] = recs[i].t - prev;
			prev = recs[i].t;
		}
		if (n > 2) {
			qsort(d, n, sizeof *d, cmp_u64);
			printf("    %s %s: %zu intervals, ms min %.3f p5 %.3f median %.3f p95 %.3f max %.3f\n",
			       label, pass ? "receive" : "kernel ", n, d[0] / 1e6, d[n / 20] / 1e6,
			       d[n / 2] / 1e6, d[n - 1 - n / 20] / 1e6, d[n - 1] / 1e6);
		}
		free(d);
	}
}

static int run_free(uint8_t phase, double secs)
{
	uint64_t end = now_ns() + (uint64_t)(secs * 1e9);
	int flips = 0;
	while (!stop && now_ns() < end) {
		if (flip(phase)) { perror("page flip"); return -1; }
		while (!stop && !wait_flips(phase, 200))
			;
		flips++;
	}
	return flips;
}

static uint64_t rng = 0x9e3779b97f4a7c15ull;
static uint64_t next_rand(void)
{
	rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17;
	return rng;
}

static double max_hz, min_hz;

/* Frame length in ns for dynamic pattern k, frame n, inside [min_hz, max_hz]. */
static uint64_t fixed_interval_ns;

static uint64_t interval(int k, unsigned n)
{
	if (k == 100)
		return fixed_interval_ns;
	uint64_t shortest = (uint64_t)(1e9 / max_hz) + 20000;
	uint64_t longest = (uint64_t)(1e9 / min_hz) - 1500000;
	uint64_t mid = (shortest + longest) / 2;
	switch (k) {
	case 0: return shortest;
	case 1: return (uint64_t)(1e9 / 55.0) > shortest && (uint64_t)(1e9 / 55.0) < longest ? (uint64_t)(1e9 / 55.0) : mid;
	case 2: return mid;
	case 3: return longest;
	case 4: return (n & 1) ? shortest : longest;
	case 5: return shortest + next_rand() % (longest - shortest + 1);
	default: return mid + (n % 20 == 19 ? 3000000 : 0);
	}
}

static int run_scheduled(uint8_t phase, int k, double secs)
{
	uint64_t start = now_ns() + 50000000ull, t = start;
	uint64_t end = start + (uint64_t)(secs * 1e9);
	int pending = 0, flips = 0, late = 0;
	for (unsigned n = 0; !stop && t < end; n++) {
		while (pending && now_ns() + 1000000 < t) {
			int ms = (int)((t - now_ns()) / 1000000) - 1;
			pending -= wait_flips(phase, ms > 0 ? ms : 0);
		}
		sleep_until(t);
		if (pending) {
			late++;
			while (!stop && pending)
				pending -= wait_flips(phase, 100);
		}
		add(phase, 'S', t);
		if (flip(phase)) { perror("page flip"); return -1; }
		pending = 1;
		flips++;
		t += interval(k, n);
	}
	while (!stop && pending)
		pending -= wait_flips(phase, 100);
	if (late)
		printf("    %d commits waited for the previous frame\n", late);
	return flips;
}

int main(int argc, char **argv)
{
	if (argc < 5) {
		fprintf(stderr, "usage: %s CONNECTOR OUT.csv SECONDS static|dynamic|all|idle|reset [vrr] [MIN_HZ]\n", argv[0]);
		return 2;
	}
	const char *conn = argv[1], *out = argv[2], *which = argv[4];
	double secs = atof(argv[3]);
	int do_reset = !strcmp(which, "reset");
	int do_idle = !strcmp(which, "idle");
	int do_static = !strcmp(which, "static") || !strcmp(which, "all");
	int do_dynamic = !strcmp(which, "dynamic") || !strcmp(which, "all");
	int vrr = argc > 5 && !strcmp(argv[5], "vrr");
	double fractions[16] = { 1.0, 0.917, 0.833, 0.75, 0.667, 0.6, 0.5 };
	size_t nfractions = 7;
	/* VRR_STATIC_HZ="55,54,53": static phases at these rates instead (phase 0 stays the mode). */
	const char *hzlist = getenv("VRR_STATIC_HZ");

	signal(SIGINT, on_signal);
	signal(SIGTERM, on_signal);
	recs = calloc(maxrecs, sizeof *recs);

	drm_fd = open("/dev/dri/card0", O_RDWR | O_CLOEXEC);
	if (drm_fd < 0) { perror("card0"); return 1; }
	struct drm_mode_modeinfo base;
	if (find_display(conn, &base)) return 1;
	W = base.hdisplay; H = base.vdisplay;
	max_hz = mode_hz(&base);
	min_hz = argc > 6 ? atof(argv[6]) : max_hz * 2 / 3;
	printf("%s mode %s: clock %u htotal %u vtotal %u (%.3f Hz), vfp %u vsw %u vbp %u, connector %u crtc %u\n",
	       conn, base.name, base.clock, base.htotal, base.vtotal, max_hz,
	       base.vsync_start - base.vdisplay, base.vsync_end - base.vsync_start,
	       base.vtotal - base.vsync_end, conn_id, crtc_id);
	if (make_buf(&bufs[0]) || make_buf(&bufs[1])) { perror("dumb buffer"); return 1; }
	uint64_t capable = 0;
	if (find_prop(conn_id, DRM_MODE_OBJECT_CONNECTOR, "vrr_capable", &capable))
		printf("connector vrr_capable %llu\n", (unsigned long long)capable);
	else
		printf("connector has no vrr_capable\n");
	if (!vrr || do_reset)
		set_vrr(0);

	if (hzlist) {
		char *dup = strdup(hzlist), *tok, *save = NULL;
		nfractions = 1;
		for (tok = strtok_r(dup, ",", &save); tok && nfractions < 16; tok = strtok_r(NULL, ",", &save))
			fractions[nfractions++] = atof(tok) / max_hz;
		free(dup);
	}
	for (size_t i = 0; do_static && i < nfractions && !stop; i++) {
		struct drm_mode_modeinfo m = base;
		if (i)
			m = stretched(&base, (int)(base.vtotal / fractions[i] + 0.5));
		int hz = (int)(mode_hz(&m) + 0.5);
		paint(&bufs[0], (int)i, hz);
		paint(&bufs[1], (int)i, hz);
		add((uint8_t)i, 'M', now_ns());
		if (set_mode(&bufs[cur], &m)) {
			printf("phase %zu: %d Hz, vtotal %u: mode set FAILED: %s\n", i, hz, m.vtotal, strerror(errno));
			continue;
		}
		add((uint8_t)i, 'm', now_ns());
		usleep(300000);
		int n = run_free((uint8_t)i, secs);
		printf("phase %zu: %.3f Hz, vtotal %u, vfp %u: %d flips in %.1f s (%.2f/s)\n",
		       i, mode_hz(&m), m.vtotal, m.vsync_start - m.vdisplay, n, secs, n / secs);
		stats((uint8_t)i, "  ");
		fflush(stdout);
	}

	if ((do_dynamic || do_reset || do_idle) && !stop) {
		struct drm_mode_modeinfo other = stretched(&base, base.vtotal + 90);
		paint(&bufs[0], 7, (int)(max_hz + 0.5));
		paint(&bufs[1], 7, (int)(max_hz + 0.5));
		if (set_mode(&bufs[cur], &other) || set_mode(&bufs[cur], &base)) {
			perror("mode set"); return 1;
		}
		if (do_reset) { printf("mode set again, VRR_ENABLED 0\n"); return 0; }
		if (vrr && set_vrr(1) == 0)
			printf("VRR_ENABLED 1, range %.1f-%.1f Hz\n", min_hz, max_hz);
		usleep(300000);
		if (do_idle) {
			if (flip(7)) { perror("page flip"); return 1; }
			while (!stop && !wait_flips(7, 200))
				;
			printf("one commit, then idle for %.0f s\n", secs);
			fflush(stdout);
			/* Count vblanks while nothing is committed: AVR should hold the floor. */
			uint64_t t0 = now_ns(), end = t0 + (uint64_t)(secs * 1e9);
			uint64_t sec_start = t0;
			unsigned vblanks = 0, sec_vblanks = 0, sec = 0;
			while (!stop && now_ns() < end) {
				if (now_ns() - sec_start >= 1000000000ull) {
					printf("  second %u: %u vblanks\n", ++sec, sec_vblanks);
					fflush(stdout);
					sec_vblanks = 0;
					sec_start += 1000000000ull;
				}
				sec_vblanks++;
				union drm_wait_vblank wv = { 0 };
				wv.request.type = _DRM_VBLANK_RELATIVE |
					((crtc_index << _DRM_VBLANK_HIGH_CRTC_SHIFT) & _DRM_VBLANK_HIGH_CRTC_MASK);
				wv.request.sequence = 1;
				if (xioctl(drm_fd, DRM_IOCTL_WAIT_VBLANK, &wv)) {
					/* a panel holding its frame sends no TE: keep counting */
					sec_vblanks--;
					usleep(2000);
					continue;
				}
				vblanks++;
			}
			printf("idle: %u vblanks in %.2f s = %.2f Hz\n", vblanks,
			       (now_ns() - t0) / 1e9, vblanks / ((now_ns() - t0) / 1e9));
			do_dynamic = 0;
		}
		/* VRR_RATES="60,50,40": instead of the patterns, one phase per rate, frames at that rate */
		const char *rates = getenv("VRR_RATES");
		if (do_dynamic && rates && *rates) {
			char *dup = strdup(rates), *tok, *save = NULL;
			uint8_t phase = 7;
			for (tok = strtok_r(dup, ",", &save); tok && !stop; tok = strtok_r(NULL, ",", &save), phase++) {
				double hz = atof(tok);
				if (hz <= 0) continue;
				fixed_interval_ns = (uint64_t)(1e9 / hz);
				paint(&bufs[0], phase, (int)(hz + 0.5));
				paint(&bufs[1], phase, (int)(hz + 0.5));
				int n = run_scheduled(phase, 100, secs);
				printf("phase %u: %.1f Hz: %d frames in %.1f s\n", phase, hz, n, secs);
				stats(phase, "  ");
				fflush(stdout);
			}
			free(dup);
			do_dynamic = 0;
		}
		static const char *names[] = { "fastest", "55 Hz", "middle", "slowest",
					       "fastest/slowest alternating", "random in range",
					       "middle, every 20th frame 3 ms late" };
		for (int k = 0; do_dynamic && k < 7 && !stop; k++) {
			uint8_t phase = (uint8_t)(7 + k);
			paint(&bufs[0], phase, (int)(1e9 / interval(k == 5 ? 2 : k, 0) + 0.5));
			paint(&bufs[1], phase, (int)(1e9 / interval(k == 5 ? 2 : k, 0) + 0.5));
			int n = run_scheduled(phase, k, secs);
			printf("phase %u: %s (%.3f ms): %d frames in %.1f s\n", phase, names[k],
			       interval(k, 1) / 1e6, n, secs);
			stats(phase, "  ");
			fflush(stdout);
		}
	}

	if (vrr)
		set_vrr(0);
	paint(&bufs[cur], 0, (int)(max_hz + 0.5));
	if (set_mode(&bufs[cur], &base)) perror("restoring the base mode");

	FILE *f = fopen(out, "w");
	if (!f) { perror(out); return 1; }
	fprintf(f, "phase,kind,t_ns\n");
	for (size_t i = 0; i < nrecs; i++)
		fprintf(f, "%u,%c,%llu\n", recs[i].phase, recs[i].kind, (unsigned long long)recs[i].t);
	fclose(f);
	printf("%zu records to %s\n", nrecs, out);
	return 0;
}
