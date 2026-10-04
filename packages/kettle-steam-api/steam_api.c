// Kettle's libsteam_api.so for ARM64: the Steam API for games run natively on ARM64 (their .NET
// or C++ code, without FEX), passed through to Steam's own ARM64 client, steamclient.so.
//
// A game ships libsteam_api.so for x86-64 only. Most of it is flat functions that call one
// virtual method of a Steam interface; steamapi-map.py reads from the game's own library which
// vtable offset each one calls and which interface version each accessor asks for, and this
// library reads that map ($KETTLE_STEAM_API_MAP) when it loads. The flat functions themselves
// are generated (gen-flat.py, flat.S): the object's vtable, the mapped offset, a jump. The rest,
// here, is the Steam API's own work: connecting to the running Steam client, interfaces, the
// context cache C++ games use, callbacks and call results (SteamAPI_RunCallbacks for C++ games,
// manual dispatch for .NET ones), and the ownership checks are Steam's own, untouched.
//
// Written from what games call and what steamclient.so exports; no Steamworks SDK code or headers.
// Game servers aren't supported (SteamGameServer_* fail as if no Steam were running).
#define _GNU_SOURCE
#include <dlfcn.h>
#include <limits.h>
#include <pthread.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

#include "flat_names.h"  // generated: kettle_flat_names[], kettle_accessor_names[]

#define EXPORT __attribute__((visibility("default")))

typedef int32_t HSteamPipe;
typedef int32_t HSteamUser;
typedef uint64_t SteamAPICall_t;
typedef char SteamErrMsg[1024];

enum { INIT_OK = 0, INIT_FAILED = 1, INIT_NO_STEAM = 2, INIT_VERSION = 3 };
enum { CALLBACK_REGISTERED = 1, CALLBACK_GAME_SERVER = 2 };
enum { API_CALL_COMPLETED = 703 };  // SteamAPICallCompleted_t

typedef struct {
    HSteamUser user;
    int callback;
    uint8_t *param;
    int size;
} CallbackMsg;

typedef struct {
    SteamAPICall_t call;
    int callback;
    uint32_t size;
} CallCompleted;

// C++ games' callback objects: a vtable (Run(param), Run(param, io_failure, call),
// GetCallbackSizeBytes()), then flags and the callback id
typedef struct {
    void **vtable;
    uint8_t flags;
    int callback;
} CallbackBase;

// SteamInternal_ContextInit's argument, in the game's own data: its init function, the counter
// it was last run for, then the context (interface pointers) the function fills in
typedef struct {
    void (*init)(void *ctx);
    uintptr_t counter;
    char ctx[];
} ContextInitData;

// ---------------------------------------------------------------- the game's map

// flat.S reads these (hidden: the library is built with -fvisibility=hidden)
uint64_t kettle_flat_off[KETTLE_FLAT_COUNT];  // vtable offset + 1 (0: not in the game's map)
static const char *accessor_version[KETTLE_ACCESSOR_COUNT];
static bool accessor_gs[KETTLE_ACCESSOR_COUNT];
static char client_version[64];
static int client_off[6];  // ISteamClient methods we call, from the map (byte offset + 1)
enum { C_CREATE_PIPE, C_RELEASE_PIPE, C_CONNECT_GLOBAL, C_RELEASE_USER, C_GENERIC, C_SHUTDOWN_PIPES };
static const char *const client_methods[] = {
    "SteamAPI_ISteamClient_CreateSteamPipe", "SteamAPI_ISteamClient_BReleaseSteamPipe",
    "SteamAPI_ISteamClient_ConnectToGlobalUser", "SteamAPI_ISteamClient_ReleaseUser",
    "SteamAPI_ISteamClient_GetISteamGenericInterface", "SteamAPI_ISteamClient_BShutdownIfAllPipesClosed",
};

static void say(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    fputs("kettle-steam-api: ", stderr);
    vfprintf(stderr, fmt, ap);
    fputc('\n', stderr);
    va_end(ap);
}

static int find(const char *const *names, int n, const char *name) {
    int lo = 0, hi = n - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2, c = strcmp(names[mid], name);
        if (!c)
            return mid;
        if (c < 0)
            lo = mid + 1;
        else
            hi = mid - 1;
    }
    return -1;
}

static bool map_loaded;

static void load_map(void) {
    const char *path = getenv("KETTLE_STEAM_API_MAP");
    FILE *f = path ? fopen(path, "r") : NULL;
    if (!f) {
        say("no map of the game's libsteam_api.so ($KETTLE_STEAM_API_MAP=%s)", path ? path : "");
        return;
    }
    char line[512], kind[16], name[256], value[160];
    int missing = 0;
    while (fgets(line, sizeof line, f)) {
        int n = sscanf(line, "%15s %255s %159s", kind, name, value);
        if (n == 2 && !strcmp(kind, "client")) {
            snprintf(client_version, sizeof client_version, "%s", name);
        } else if (n == 3 && !strcmp(kind, "forward")) {
            int i = find(kettle_flat_names, KETTLE_FLAT_COUNT, name);
            unsigned long off = strtoul(value, NULL, 10);
            if (i >= 0)
                kettle_flat_off[i] = off + 1;
            else
                missing++;
            for (int c = 0; c < 6; c++)
                if (!strcmp(name, client_methods[c]))
                    client_off[c] = (int)off + 1;
        } else if (n == 3 && (!strcmp(kind, "user") || !strcmp(kind, "gs"))) {
            int i = find(kettle_accessor_names, KETTLE_ACCESSOR_COUNT, name);
            if (i >= 0) {
                accessor_version[i] = strdup(value);
                accessor_gs[i] = kind[0] == 'g';
            } else {
                missing++;
            }
        }
    }
    fclose(f);
    if (missing)
        say("%d functions of the game's library are unknown here", missing);
    map_loaded = client_version[0] && client_off[C_CREATE_PIPE] && client_off[C_CONNECT_GLOBAL] &&
                 client_off[C_GENERIC];
    if (!map_loaded)
        say("the map has no SteamClient version or methods: %s", path);
}

__attribute__((constructor)) static void kettle_steam_api_load(void) { load_map(); }

// A flat function the game's library has but its map couldn't say how to pass on (flat.S)
void kettle_flat_missing(int i) {
    say("%s: not passed through (not a plain virtual call in the game's library)", kettle_flat_names[i]);
    abort();
}

// ---------------------------------------------------------------- Steam

static pthread_mutex_t lock = PTHREAD_RECURSIVE_MUTEX_INITIALIZER_NP;
static void *steamclient;
static void *(*CreateInterface)(const char *version, int *ret);
static bool (*BGetCallback)(HSteamPipe, CallbackMsg *);
static void (*FreeLastCallback)(HSteamPipe);
static bool (*GetAPICallResult)(HSteamPipe, SteamAPICall_t, void *, int, int, bool *);
static void (*ReleaseThreadLocalMemory)(int);
static void *client;  // ISteamClient
static HSteamPipe pipe_;
static HSteamUser user_;
static uintptr_t counter;  // ContextInit: bumped by every init and shutdown
static bool manual_dispatch;

#define VCALL(obj, which, type) ((type)((*(void ***)(obj))[(client_off[which] - 1) / sizeof(void *)]))

static const char *home(void) {
    const char *h = getenv("HOME");
    return h ? h : "/";
}

EXPORT bool SteamAPI_IsSteamRunning(void) {
    char path[PATH_MAX];
    snprintf(path, sizeof path, "%s/.steam/steam.pid", home());
    FILE *f = fopen(path, "r");
    long pid = 0;
    if (f) {
        if (fscanf(f, "%ld", &pid) != 1)
            pid = 0;
        fclose(f);
    }
    return pid > 0 && kill((pid_t)pid, 0) == 0;
}

EXPORT const char *SteamAPI_GetSteamInstallPath(void) {
    static char path[PATH_MAX];
    char link[PATH_MAX];
    snprintf(link, sizeof link, "%s/.steam/root", home());
    if (!realpath(link, path))
        snprintf(path, sizeof path, "%s/.local/share/Steam", home());
    return path;
}

static bool load_steamclient(char *err, size_t errlen) {
    if (steamclient)
        return true;
    const char *dirs[] = {"/.steam/sdkarm64", "/.local/share/Steam/linuxarm64"};
    char path[PATH_MAX];
    for (unsigned i = 0; i < 2 && !steamclient; i++) {
        snprintf(path, sizeof path, "%s%s/steamclient.so", home(), dirs[i]);
        steamclient = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    }
    if (!steamclient) {
        snprintf(err, errlen, "Steam's ARM64 steamclient.so isn't there: %s", dlerror());
        return false;
    }
    CreateInterface = dlsym(steamclient, "CreateInterface");
    BGetCallback = dlsym(steamclient, "Steam_BGetCallback");
    FreeLastCallback = dlsym(steamclient, "Steam_FreeLastCallback");
    GetAPICallResult = dlsym(steamclient, "Steam_GetAPICallResult");
    ReleaseThreadLocalMemory = dlsym(steamclient, "Steam_ReleaseThreadLocalMemory");
    if (!CreateInterface || !BGetCallback || !FreeLastCallback || !GetAPICallResult) {
        snprintf(err, errlen, "steamclient.so lacks the functions the Steam API uses");
        dlclose(steamclient);
        steamclient = NULL;
        return false;
    }
    return true;
}

static int init(const char *versions, char *err, size_t errlen) {
    pthread_mutex_lock(&lock);
    int ret = INIT_OK;
    if (user_)
        goto out;
    if (!map_loaded) {
        snprintf(err, errlen, "no map of the game's libsteam_api.so (KETTLE_STEAM_API_MAP)");
        ret = INIT_FAILED;
        goto out;
    }
    if (!SteamAPI_IsSteamRunning()) {
        snprintf(err, errlen, "Steam isn't running");
        ret = INIT_NO_STEAM;
        goto out;
    }
    if (!load_steamclient(err, errlen)) {
        ret = INIT_NO_STEAM;
        goto out;
    }
    client = CreateInterface(client_version, NULL);
    if (!client) {
        snprintf(err, errlen, "Steam has no %s", client_version);
        ret = INIT_VERSION;
        goto out;
    }
    pipe_ = VCALL(client, C_CREATE_PIPE, HSteamPipe (*)(void *))(client);
    user_ = pipe_ ? VCALL(client, C_CONNECT_GLOBAL, HSteamUser (*)(void *, HSteamPipe))(client, pipe_) : 0;
    if (!user_) {
        if (pipe_ && client_off[C_RELEASE_PIPE])
            VCALL(client, C_RELEASE_PIPE, bool (*)(void *, HSteamPipe))(client, pipe_);
        pipe_ = 0;
        snprintf(err, errlen, "couldn't connect to the Steam user (not logged in?)");
        ret = INIT_NO_STEAM;
        goto out;
    }
    // the interface versions the game's code needs (newer SDKs pass them, NUL separated)
    for (const char *v = versions; v && *v; v += strlen(v) + 1) {
        void *i = VCALL(client, C_GENERIC, void *(*)(void *, HSteamUser, HSteamPipe, const char *))(client, user_, pipe_, v);
        if (!i) {
            snprintf(err, errlen, "Steam has no interface %s", v);
            say("%s", err);  // not fatal: the game may never use it
        }
    }
    counter++;
    say("connected to Steam (%s, pipe %d, user %d)", client_version, pipe_, user_);
out:
    if (ret != INIT_OK)
        say("%s", err);
    pthread_mutex_unlock(&lock);
    return ret;
}

EXPORT int SteamInternal_SteamAPI_Init(const char *versions, SteamErrMsg *err) {
    SteamErrMsg tmp;
    return init(versions, err ? *err : tmp, sizeof tmp);
}

EXPORT int SteamAPI_InitFlat(SteamErrMsg *err) { return SteamInternal_SteamAPI_Init(NULL, err); }

EXPORT bool SteamAPI_Init(void) { return SteamInternal_SteamAPI_Init(NULL, NULL) == INIT_OK; }
EXPORT bool SteamAPI_InitSafe(void) { return SteamAPI_Init(); }
EXPORT bool SteamAPI_InitAnonymousUser(void) { return false; }

EXPORT void SteamAPI_Shutdown(void) {
    pthread_mutex_lock(&lock);
    if (user_) {
        if (client_off[C_RELEASE_USER])
            VCALL(client, C_RELEASE_USER, void (*)(void *, HSteamPipe, HSteamUser))(client, pipe_, user_);
        if (client_off[C_RELEASE_PIPE])
            VCALL(client, C_RELEASE_PIPE, bool (*)(void *, HSteamPipe))(client, pipe_);
        if (client_off[C_SHUTDOWN_PIPES])
            VCALL(client, C_SHUTDOWN_PIPES, bool (*)(void *))(client);
        user_ = pipe_ = 0;
        counter++;
    }
    pthread_mutex_unlock(&lock);
}

// A game started outside Steam asks Steam to start it: Steam sets SteamAppId for its games
EXPORT bool SteamAPI_RestartAppIfNecessary(uint32_t appid) {
    if (getenv("SteamAppId") || getenv("SteamGameId") || access("steam_appid.txt", F_OK) == 0)
        return false;
    say("not started by Steam: asking Steam to start app %u", appid);
    if (fork() == 0) {
        char url[64];
        snprintf(url, sizeof url, "steam://run/%u", appid);
        execlp("steam", "steam", url, (char *)NULL);
        execlp("xdg-open", "xdg-open", url, (char *)NULL);
        _exit(127);
    }
    return true;
}

EXPORT HSteamPipe SteamAPI_GetHSteamPipe(void) { return pipe_; }
EXPORT HSteamUser SteamAPI_GetHSteamUser(void) { return user_; }
EXPORT HSteamPipe GetHSteamPipe(void) { return pipe_; }
EXPORT HSteamUser GetHSteamUser(void) { return user_; }
EXPORT void *SteamClient(void) { return client; }

EXPORT void SteamAPI_ReleaseCurrentThreadMemory(void) {
    if (ReleaseThreadLocalMemory)
        ReleaseThreadLocalMemory(0);
}

// ---------------------------------------------------------------- interfaces

static void *interface(HSteamUser user, const char *version) {
    if (!client || !user || !version)
        return NULL;
    return VCALL(client, C_GENERIC, void *(*)(void *, HSteamUser, HSteamPipe, const char *))(client, user, pipe_, version);
}

EXPORT void *SteamInternal_FindOrCreateUserInterface(HSteamUser user, const char *version) {
    return interface(user, version);
}

EXPORT void *SteamInternal_FindOrCreateGameServerInterface(HSteamUser user, const char *version) {
    (void)user;
    (void)version;
    return NULL;
}

EXPORT void *SteamInternal_CreateInterface(const char *version) {
    if (version && !strncmp(version, "SteamClient", 11))
        return CreateInterface ? CreateInterface(version, NULL) : NULL;
    return interface(user_, version);
}

EXPORT void *SteamInternal_ContextInit(void *data) {
    ContextInitData *d = data;
    if (d->counter != counter) {
        pthread_mutex_lock(&lock);
        if (d->counter != counter) {
            if (user_)
                d->init(d->ctx);
            d->counter = counter;
        }
        pthread_mutex_unlock(&lock);
    }
    return d->ctx;
}

// SteamAPI_Steam<Interface>_v<N>() (flat.S passes which one)
void *kettle_accessor(int i) {
    if (i < 0 || i >= KETTLE_ACCESSOR_COUNT || !accessor_version[i] || accessor_gs[i])
        return NULL;
    return interface(user_, accessor_version[i]);
}

// ---------------------------------------------------------------- networking helpers
// ISteamNetworkingUtils' convenience functions: inline in the API, so each game's library has
// its own copy of them built on the interface's virtual methods (SetConfigValue and others),
// which are in the map like any other. The values below are the API's public enum values
// (also seen in the games' own libraries).

enum { SCOPE_GLOBAL = 1, SCOPE_CONNECTION = 4 };
enum { TYPE_INT32 = 1, TYPE_FLOAT = 3, TYPE_STRING = 4, TYPE_PTR = 5 };
#define UTILS "SteamAPI_ISteamNetworkingUtils_"

static long method(const char *name) {
    int i = find(kettle_flat_names, KETTLE_FLAT_COUNT, name);
    if (i < 0 || !kettle_flat_off[i]) {
        say("%s: not in the game's map", name);
        return -1;
    }
    return (long)kettle_flat_off[i] - 1;
}

#define METHOD(self, off, type) ((type)((*(void ***)(self))[(off) / sizeof(void *)]))

static bool set_config(void *self, int value, int scope, intptr_t obj, int type, const void *arg) {
    static long off = -2;
    if (off == -2)
        off = method(UTILS "SetConfigValue");
    if (off < 0)
        return false;
    return METHOD(self, off, bool (*)(void *, int, int, intptr_t, int, const void *))(self, value, scope, obj, type, arg);
}

EXPORT bool SteamAPI_ISteamNetworkingUtils_SetGlobalConfigValueInt32(void *s, int value, int32_t v) {
    return set_config(s, value, SCOPE_GLOBAL, 0, TYPE_INT32, &v);
}
EXPORT bool SteamAPI_ISteamNetworkingUtils_SetGlobalConfigValueFloat(void *s, int value, float v) {
    return set_config(s, value, SCOPE_GLOBAL, 0, TYPE_FLOAT, &v);
}
EXPORT bool SteamAPI_ISteamNetworkingUtils_SetGlobalConfigValueString(void *s, int value, const char *v) {
    return set_config(s, value, SCOPE_GLOBAL, 0, TYPE_STRING, v);
}
EXPORT bool SteamAPI_ISteamNetworkingUtils_SetGlobalConfigValuePtr(void *s, int value, void *v) {
    return set_config(s, value, SCOPE_GLOBAL, 0, TYPE_PTR, &v);
}
EXPORT bool SteamAPI_ISteamNetworkingUtils_SetConnectionConfigValueInt32(void *s, uint32_t conn, int value, int32_t v) {
    return set_config(s, value, SCOPE_CONNECTION, conn, TYPE_INT32, &v);
}
EXPORT bool SteamAPI_ISteamNetworkingUtils_SetConnectionConfigValueFloat(void *s, uint32_t conn, int value, float v) {
    return set_config(s, value, SCOPE_CONNECTION, conn, TYPE_FLOAT, &v);
}
EXPORT bool SteamAPI_ISteamNetworkingUtils_SetConnectionConfigValueString(void *s, uint32_t conn, int value,
                                                                          const char *v) {
    return set_config(s, value, SCOPE_CONNECTION, conn, TYPE_STRING, v);
}

#define GLOBAL_CALLBACK(name, id)                                                    \
    EXPORT bool SteamAPI_ISteamNetworkingUtils_SetGlobalCallback_##name(void *s, void *fn) { \
        return set_config(s, id, SCOPE_GLOBAL, 0, TYPE_PTR, &fn);                    \
    }
GLOBAL_CALLBACK(SteamNetConnectionStatusChanged, 201)
GLOBAL_CALLBACK(SteamNetAuthenticationStatusChanged, 202)
GLOBAL_CALLBACK(SteamRelayNetworkStatusChanged, 203)
GLOBAL_CALLBACK(MessagesSessionRequest, 204)
GLOBAL_CALLBACK(MessagesSessionFailed, 205)
GLOBAL_CALLBACK(FakeIPResult, 207)

// SteamNetworkingConfigValue_t: which value, its type, then the value (a string by its pointer)
typedef struct {
    int value;
    int type;
    union {
        int32_t i32;
        int64_t i64;
        float f;
        const char *str;
        void *ptr;
    } v;
} ConfigValue;

EXPORT bool SteamAPI_ISteamNetworkingUtils_SetConfigValueStruct(void *s, const ConfigValue *opt, int scope,
                                                                intptr_t obj) {
    return set_config(s, opt->value, scope, obj, opt->type, opt->type == TYPE_STRING ? (const void *)opt->v.str
                                                                                     : (const void *)&opt->v);
}

// Relay network access: ping data of any age (the API's own helper asks for 1e10 seconds)
EXPORT void SteamAPI_ISteamNetworkingUtils_InitRelayNetworkAccess(void *s) {
    long off = method(UTILS "CheckPingDataUpToDate");
    if (off >= 0)
        METHOD(s, off, bool (*)(void *, float))(s, 1e10f);
}

EXPORT bool SteamAPI_ISteamNetworkingUtils_IsFakeIPv4(void *s, uint32_t ip) {
    long off = method(UTILS "GetIPv4FakeIPType");
    return off >= 0 && METHOD(s, off, int (*)(void *, uint32_t))(s, ip) > 1;  // k_ESteamNetworkingFakeIPType_FakeIP
}

// ---------------------------------------------------------------- callbacks

typedef struct {
    CallbackBase *cb;
    SteamAPICall_t call;  // 0: a callback, else the call result it waits for
} Registration;

static Registration *regs;
static size_t nregs, cregs;

static void add_reg(CallbackBase *cb, SteamAPICall_t call) {
    pthread_mutex_lock(&lock);
    if (nregs == cregs) {
        cregs = cregs ? cregs * 2 : 64;
        regs = realloc(regs, cregs * sizeof *regs);
    }
    regs[nregs++] = (Registration){cb, call};
    pthread_mutex_unlock(&lock);
}

static void remove_reg(CallbackBase *cb, SteamAPICall_t call, bool any_call) {
    pthread_mutex_lock(&lock);
    for (size_t i = 0; i < nregs;) {
        if (regs[i].cb == cb && (any_call ? regs[i].call == 0 : regs[i].call == call))
            regs[i] = regs[--nregs];
        else
            i++;
    }
    pthread_mutex_unlock(&lock);
}

EXPORT void SteamAPI_RegisterCallback(CallbackBase *cb, int callback) {
    cb->callback = callback;
    cb->flags |= CALLBACK_REGISTERED;
    add_reg(cb, 0);
}

EXPORT void SteamAPI_UnregisterCallback(CallbackBase *cb) {
    cb->flags &= ~CALLBACK_REGISTERED;
    remove_reg(cb, 0, true);
}

EXPORT void SteamAPI_RegisterCallResult(CallbackBase *cb, SteamAPICall_t call) {
    if (call)
        add_reg(cb, call);
}

EXPORT void SteamAPI_UnregisterCallResult(CallbackBase *cb, SteamAPICall_t call) { remove_reg(cb, call, false); }

static void run(CallbackBase *cb, void *param) { ((void (*)(CallbackBase *, void *))cb->vtable[0])(cb, param); }

static void run_result(CallbackBase *cb, void *param, bool failed, SteamAPICall_t call) {
    ((void (*)(CallbackBase *, void *, bool, SteamAPICall_t))cb->vtable[1])(cb, param, failed, call);
}

// Callbacks and call results for C++ games' registered objects (.NET games dispatch manually)
EXPORT void SteamAPI_RunCallbacks(void) {
    if (!pipe_ || manual_dispatch)
        return;
    pthread_mutex_lock(&lock);
    CallbackMsg msg;
    while (pipe_ && BGetCallback(pipe_, &msg)) {
        if (msg.callback == API_CALL_COMPLETED && msg.size >= (int)sizeof(CallCompleted)) {
            CallCompleted *c = (CallCompleted *)msg.param;
            for (size_t i = 0; i < nregs; i++) {
                if (regs[i].call != c->call)
                    continue;
                CallbackBase *cb = regs[i].cb;
                regs[i] = regs[--nregs];
                void *buf = calloc(1, c->size ? c->size : 1);
                bool failed = false;
                if (GetAPICallResult(pipe_, c->call, buf, (int)c->size, c->callback, &failed))
                    run_result(cb, buf, failed, c->call);
                free(buf);
                break;
            }
        }
        // a copy: a callback may register or unregister others
        size_t n = nregs;
        Registration *now = malloc((n ? n : 1) * sizeof *now);
        memcpy(now, regs, n * sizeof *now);
        for (size_t i = 0; i < n; i++)
            if (!now[i].call && now[i].cb->callback == msg.callback && !(now[i].cb->flags & CALLBACK_GAME_SERVER))
                run(now[i].cb, msg.param);
        free(now);
        FreeLastCallback(pipe_);
    }
    pthread_mutex_unlock(&lock);
}

EXPORT void SteamAPI_ManualDispatch_Init(void) { manual_dispatch = true; }
EXPORT void SteamAPI_ManualDispatch_RunFrame(HSteamPipe pipe) { (void)pipe; }

EXPORT bool SteamAPI_ManualDispatch_GetNextCallback(HSteamPipe pipe, CallbackMsg *msg) {
    return pipe && BGetCallback && BGetCallback(pipe, msg);
}

EXPORT void SteamAPI_ManualDispatch_FreeLastCallback(HSteamPipe pipe) {
    if (pipe && FreeLastCallback)
        FreeLastCallback(pipe);
}

EXPORT bool SteamAPI_ManualDispatch_GetAPICallResult(HSteamPipe pipe, SteamAPICall_t call, void *out, int size,
                                                     int callback, bool *failed) {
    return pipe && GetAPICallResult && GetAPICallResult(pipe, call, out, size, callback, failed);
}

// ---------------------------------------------------------------- the rest: nothing to do here

EXPORT void SteamAPI_SetTryCatchCallbacks(bool on) { (void)on; }
EXPORT void SteamAPI_UseBreakpadCrashHandler(const char *v, const char *d, const char *t, bool full, void *ctx,
                                             void *pre) {
    (void)v, (void)d, (void)t, (void)full, (void)ctx, (void)pre;
}
EXPORT void SteamAPI_SetBreakpadAppID(uint32_t appid) { (void)appid; }
EXPORT void SteamAPI_SetMiniDumpComment(const char *msg) { (void)msg; }
EXPORT void SteamAPI_WriteMiniDump(uint32_t code, void *info, uint32_t build) { (void)code, (void)info, (void)build; }

// game servers: not supported
EXPORT void *g_pSteamClientGameServer;
EXPORT int SteamInternal_GameServer_Init_V2(uint32_t ip, uint16_t game_port, uint16_t query_port, int mode,
                                            const char *version, const char *versions, SteamErrMsg *err) {
    (void)ip, (void)game_port, (void)query_port, (void)mode, (void)version, (void)versions;
    if (err)
        snprintf(*err, sizeof *err, "game servers aren't supported on ARM64");
    return INIT_FAILED;
}
EXPORT bool SteamInternal_GameServer_Init(uint32_t ip, uint16_t a, uint16_t g, uint16_t q, int mode,
                                          const char *version) {
    (void)ip, (void)a, (void)g, (void)q, (void)mode, (void)version;
    return false;
}
EXPORT bool SteamGameServer_InitSafe(uint32_t ip, uint16_t a, uint16_t g, uint16_t q, int mode, const char *v) {
    return SteamInternal_GameServer_Init(ip, a, g, q, mode, v);
}
EXPORT void SteamGameServer_Shutdown(void) {}
EXPORT void SteamGameServer_RunCallbacks(void) {}
EXPORT bool SteamGameServer_BSecure(void) { return false; }
EXPORT uint64_t SteamGameServer_GetSteamID(void) { return 0; }
EXPORT HSteamPipe SteamGameServer_GetHSteamPipe(void) { return 0; }
EXPORT HSteamUser SteamGameServer_GetHSteamUser(void) { return 0; }
EXPORT uint32_t SteamGameServer_GetIPCCallCount(void) { return 0; }
