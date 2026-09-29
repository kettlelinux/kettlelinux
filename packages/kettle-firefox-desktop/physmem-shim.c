// Preloaded into Firefox (kettle-firefox): answers sysconf(_SC_PHYS_PAGES) with the value read
// when the process started, before Firefox's sandbox.
//
// Why: Firefox's media decoder process (RDD) checks its first hardware-decoded frame by making a
// GL texture from it. Mesa here is zink only (GL on turnip), and zink refuses to start without the
// total RAM size, which glibc gets from sysinfo(); Firefox's seccomp policy answers sysinfo() with
// EPERM outside content processes. So the check failed and Firefox fell back to software decoding.
#define _GNU_SOURCE
#include <dlfcn.h>
#include <unistd.h>

static long (*real_sysconf)(int);
static long phys_pages;

__attribute__((constructor)) static void init(void)
{
	real_sysconf = (long (*)(int))dlsym(RTLD_NEXT, "sysconf");
	if (real_sysconf)
		phys_pages = real_sysconf(_SC_PHYS_PAGES);
}

long sysconf(int name)
{
	if (name == _SC_PHYS_PAGES && phys_pages > 0)
		return phys_pages;
	if (!real_sysconf)
		init();
	return real_sysconf ? real_sysconf(name) : -1;
}
