/* libkettle_affinity: an LD_PRELOAD library that moves a game's CPU pins off the little cores.
 *
 * Some games pin their busiest threads to fixed CPU numbers chosen for a desktop PC, where every
 * core is equally fast. On SM8550 cpus 0-2 are A510 little cores (about a fifth of the prime
 * core's speed): Baldur's Gate 3's native Linux build puts GameThread on cpu 1 and ServerWorker
 * on cpu 2 and runs Act 3 at 20 fps. This library rewrites the masks the game passes to
 * sched_setaffinity, pthread_setaffinity_np and pthread_attr_setaffinity_np:
 *   - a CPU named in KETTLE_AFFINITY_MAP goes where the map says ("1=7,2=3,0=3-6": cpu 1 -> 7,
 *     cpu 2 -> 3, cpu 0 -> 3 to 6; a destination is one CPU or one range);
 *   - any other little core becomes all the fast cores, so the scheduler places the thread;
 *   - fast cores stay as they are, so a mask of only fast cores (Valve's 3-7) is untouched.
 * Little cores are the CPUs with the lowest cpu_capacity, when capacities differ. With
 * KETTLE_AFFINITY_LOG=1 each rewrite is printed on stderr.
 *
 * No system headers: the same file builds for x86_64 (games under FEX, whose glibc is the Steam
 * Runtime's) and for aarch64. The calls it makes are glibc's, resolved when the game loads it. */

typedef unsigned long size_t;
typedef unsigned long u64;
typedef unsigned long pthread_t;

#define EXPORT __attribute__((visibility("default")))
#define RTLD_NEXT ((void *)-1l)
#define MAXCPU 64

extern void *dlsym(void *, const char *);
extern char *getenv(const char *);
extern int open(const char *, int, ...);
extern long read(int, void *, size_t);
extern long write(int, const void *, size_t);
extern int close(int);
extern int pthread_getname_np(pthread_t, char *, size_t);
extern pthread_t pthread_self(void);

static int active;     /* 1 when there are little cores to move threads off */
static u64 little;     /* little cores */
static u64 fast;       /* every other core */
static u64 map[MAXCPU]; /* per source CPU: its destination cores, 0 = no rule */
static int logging;

static int num(const char **s) {
  int n = -1;
  while (**s >= '0' && **s <= '9') n = (n < 0 ? 0 : n * 10) + *(*s)++ - '0';
  return n;
}

static int capacity(int cpu) {
  char path[64] = "/sys/devices/system/cpu/cpu", buf[16];
  char *p = path + 27;
  if (cpu >= 10) *p++ = '0' + cpu / 10;
  *p++ = '0' + cpu % 10;
  const char *tail = "/cpu_capacity";
  while ((*p++ = *tail++));
  int fd = open(path, 0);
  if (fd < 0) return -1;
  long n = read(fd, buf, sizeof buf - 1);
  close(fd);
  if (n <= 0) return -1;
  buf[n] = 0;
  const char *b = buf;
  return num(&b);
}

static void out(const char *s) {
  size_t n = 0;
  while (s[n]) n++;
  write(2, s, n);
}

static void hex(char *p, u64 v) {
  int i = 0;
  char t[16];
  do t[i++] = "0123456789abcdef"[v & 15]; while (v >>= 4);
  *p++ = '0', *p++ = 'x';
  while (i) *p++ = t[--i];
  *p = 0;
}

__attribute__((constructor)) static void init(void) {
  int cap[MAXCPU], lo = 1 << 30, hi = -1, n = 0;
  for (; n < MAXCPU && (cap[n] = capacity(n)) >= 0; n++) {
    if (cap[n] < lo) lo = cap[n];
    if (cap[n] > hi) hi = cap[n];
  }
  if (n == 0 || lo == hi) return;
  for (int i = 0; i < n; i++) {
    if (cap[i] == lo) little |= 1ul << i;
    else fast |= 1ul << i;
  }
  /* KETTLE_AFFINITY_MAP: src=dst[-dst2], comma separated */
  const char *s = getenv("KETTLE_AFFINITY_MAP");
  while (s && *s) {
    int src = num(&s), a = -1, b;
    if (*s == '=') s++, a = num(&s);
    b = a;
    if (*s == '-') s++, b = num(&s);
    if (src >= 0 && src < n && a >= 0 && b >= a && b < n)
      for (int i = a; i <= b; i++) map[src] |= 1ul << i;
    while (*s && *s != ',') s++;
    if (*s) s++;
  }
  const char *l = getenv("KETTLE_AFFINITY_LOG");
  logging = l && *l == '1';
  active = 1;
}

/* the rewritten copy of mask in buf; mask itself when nothing changes */
static const void *remap(const char *what, pthread_t thread, size_t size, const void *mask, u64 *buf) {
  if (!active || !mask || size < sizeof(u64) || size > 128) return mask;
  u64 in = *(const u64 *)mask, res = 0;
  for (int i = 0; i < MAXCPU; i++) {
    if (!(in >> i & 1)) continue;
    if (map[i]) res |= map[i];
    else if (little >> i & 1) res |= fast;
    else res |= 1ul << i;
  }
  if (res == in || !res) return mask;
  const char *m = mask;
  char *d = (char *)buf;
  for (size_t i = 0; i < size; i++) d[i] = m[i];
  buf[0] = res;
  if (logging) {
    char name[32] = "", a[24], b[24];
    if (thread) pthread_getname_np(thread, name, sizeof name);
    hex(a, in), hex(b, res);
    out("kettle-affinity: "), out(what), out(" "), out(name), out(" "), out(a), out(" -> "),
        out(b), out("\n");
  }
  return buf;
}

EXPORT int sched_setaffinity(int pid, size_t size, const void *mask) {
  static int (*real)(int, size_t, const void *);
  if (!real) real = dlsym(RTLD_NEXT, "sched_setaffinity");
  u64 buf[16];
  return real(pid, size, remap("sched_setaffinity", pid ? 0 : pthread_self(), size, mask, buf));
}

EXPORT int pthread_setaffinity_np(pthread_t thread, size_t size, const void *mask) {
  static int (*real)(pthread_t, size_t, const void *);
  if (!real) real = dlsym(RTLD_NEXT, "pthread_setaffinity_np");
  u64 buf[16];
  return real(thread, size, remap("pthread_setaffinity_np", thread, size, mask, buf));
}

EXPORT int pthread_attr_setaffinity_np(void *attr, size_t size, const void *mask) {
  static int (*real)(void *, size_t, const void *);
  if (!real) real = dlsym(RTLD_NEXT, "pthread_attr_setaffinity_np");
  u64 buf[16];
  return real(attr, size, remap("pthread_attr_setaffinity_np", 0, size, mask, buf));
}
