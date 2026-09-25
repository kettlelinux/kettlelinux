// SPDX-License-Identifier: BSD-3-Clause
// VK_LAYER_KETTLE_lsfg_noubwc: keeps the images lsfg-vk shares between the game's
// VkDevice and its own frame generation VkDevice (external opaque-fd memory) uncompressed.
// With UBWC on those images the Adreno 740 shows blocky generated frames; TU_DEBUG=noubwc
// avoided that by turning UBWC off for every image the game has. Here only the shared
// images lose it, through VK_EXT_image_compression_control (VK_IMAGE_COMPRESSION_DISABLED_EXT).
//
// Loaded only with KETTLE_LSFG_NOUBWC=1 (set per game by the Frame Generation plugin).
// It has to sit below lsfg-vk in the layer chain to see the images lsfg-vk imports into the
// game's device; the manifest name sorts after lsfg-vk's for that.
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <vulkan/vulkan.h>
#include <vulkan/vk_layer.h>

#define EXPORT __attribute__((visibility("default")))
#define LAYER "VK_LAYER_KETTLE_lsfg_noubwc"
#define KEY(h) (*(void **)(h))

struct inst {
    struct inst *next;
    void *key;
    VkInstance handle;
    PFN_vkGetInstanceProcAddr gipa;
    PFN_vkDestroyInstance destroy;
    PFN_vkEnumerateDeviceExtensionProperties enum_dev_ext;
};

struct dev {
    struct dev *next;
    void *key;
    PFN_vkGetDeviceProcAddr gdpa;
    PFN_vkDestroyDevice destroy;
    PFN_vkCreateImage create_image;
    bool compression_control;
};

static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static struct inst *insts;
static struct dev *devs;

static struct inst *find_inst(void *key)
{
    pthread_mutex_lock(&lock);
    struct inst *i = insts;
    while (i && i->key != key)
        i = i->next;
    pthread_mutex_unlock(&lock);
    return i;
}

static struct dev *find_dev(void *key)
{
    pthread_mutex_lock(&lock);
    struct dev *d = devs;
    while (d && d->key != key)
        d = d->next;
    pthread_mutex_unlock(&lock);
    return d;
}

static void *unlink_key(void **list, void *key)
{
    // both structs start with {next, key}
    struct node { struct node *next; void *key; };
    pthread_mutex_lock(&lock);
    struct node **p = (struct node **)list, *n;
    while ((n = *p) && n->key != key)
        p = &n->next;
    if (n)
        *p = n->next;
    pthread_mutex_unlock(&lock);
    return n;
}

static const void *find_struct(const void *chain, VkStructureType type)
{
    for (const VkBaseInStructure *s = chain; s; s = s->pNext)
        if (s->sType == type)
            return s;
    return NULL;
}

static VKAPI_ATTR VkResult VKAPI_CALL CreateInstance(const VkInstanceCreateInfo *ci,
                                                     const VkAllocationCallbacks *alloc,
                                                     VkInstance *out)
{
    VkLayerInstanceCreateInfo *link = (VkLayerInstanceCreateInfo *)ci->pNext;
    while (link && !(link->sType == VK_STRUCTURE_TYPE_LOADER_INSTANCE_CREATE_INFO &&
                     link->function == VK_LAYER_LINK_INFO))
        link = (VkLayerInstanceCreateInfo *)link->pNext;
    if (!link)
        return VK_ERROR_INITIALIZATION_FAILED;
    PFN_vkGetInstanceProcAddr gipa = link->u.pLayerInfo->pfnNextGetInstanceProcAddr;
    link->u.pLayerInfo = link->u.pLayerInfo->pNext;

    PFN_vkCreateInstance create = (PFN_vkCreateInstance)gipa(NULL, "vkCreateInstance");
    VkResult r = create(ci, alloc, out);
    if (r != VK_SUCCESS)
        return r;

    struct inst *i = calloc(1, sizeof(*i));
    if (!i) {
        ((PFN_vkDestroyInstance)gipa(*out, "vkDestroyInstance"))(*out, alloc);
        return VK_ERROR_OUT_OF_HOST_MEMORY;
    }
    i->key = KEY(*out);
    i->handle = *out;
    i->gipa = gipa;
    i->destroy = (PFN_vkDestroyInstance)gipa(*out, "vkDestroyInstance");
    i->enum_dev_ext = (PFN_vkEnumerateDeviceExtensionProperties)
        gipa(*out, "vkEnumerateDeviceExtensionProperties");
    pthread_mutex_lock(&lock);
    i->next = insts;
    insts = i;
    pthread_mutex_unlock(&lock);
    return VK_SUCCESS;
}

static VKAPI_ATTR void VKAPI_CALL DestroyInstance(VkInstance instance,
                                                  const VkAllocationCallbacks *alloc)
{
    if (!instance)
        return;
    struct inst *i = unlink_key((void **)&insts, KEY(instance));
    if (i) {
        i->destroy(instance, alloc);
        free(i);
    }
}

static bool has_extension(struct inst *i, VkPhysicalDevice phys, const char *name)
{
    uint32_t n = 0;
    if (i->enum_dev_ext(phys, NULL, &n, NULL) != VK_SUCCESS || !n)
        return false;
    VkExtensionProperties *props = calloc(n, sizeof(*props));
    bool found = false;
    if (props && i->enum_dev_ext(phys, NULL, &n, props) == VK_SUCCESS)
        for (uint32_t k = 0; k < n && !found; k++)
            found = !strcmp(props[k].extensionName, name);
    free(props);
    return found;
}

static VKAPI_ATTR VkResult VKAPI_CALL CreateDevice(VkPhysicalDevice phys,
                                                   const VkDeviceCreateInfo *ci,
                                                   const VkAllocationCallbacks *alloc,
                                                   VkDevice *out)
{
    VkLayerDeviceCreateInfo *link = (VkLayerDeviceCreateInfo *)ci->pNext;
    while (link && !(link->sType == VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO &&
                     link->function == VK_LAYER_LINK_INFO))
        link = (VkLayerDeviceCreateInfo *)link->pNext;
    struct inst *i = find_inst(KEY(phys));
    if (!link || !i)
        return VK_ERROR_INITIALIZATION_FAILED;
    PFN_vkGetInstanceProcAddr gipa = link->u.pLayerInfo->pfnNextGetInstanceProcAddr;
    PFN_vkGetDeviceProcAddr gdpa = link->u.pLayerInfo->pfnNextGetDeviceProcAddr;
    link->u.pLayerInfo = link->u.pLayerInfo->pNext;
    PFN_vkCreateDevice create = (PFN_vkCreateDevice)gipa(i->handle, "vkCreateDevice");

    // Enable VK_EXT_image_compression_control (extension + feature) unless already enabled
    const char *ext = VK_EXT_IMAGE_COMPRESSION_CONTROL_EXTENSION_NAME;
    bool enabled = false;
    for (uint32_t k = 0; k < ci->enabledExtensionCount; k++)
        enabled |= !strcmp(ci->ppEnabledExtensionNames[k], ext);
    const VkPhysicalDeviceImageCompressionControlFeaturesEXT *feat =
        find_struct(ci->pNext, VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_IMAGE_COMPRESSION_CONTROL_FEATURES_EXT);
    bool usable = has_extension(i, phys, ext);

    VkDeviceCreateInfo ci2 = *ci;
    const char **names = NULL;
    VkPhysicalDeviceImageCompressionControlFeaturesEXT feat2 = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_IMAGE_COMPRESSION_CONTROL_FEATURES_EXT,
        .pNext = (void *)ci->pNext,
        .imageCompressionControl = VK_TRUE,
    };
    if (usable && !enabled) {
        names = malloc((ci->enabledExtensionCount + 1) * sizeof(*names));
        if (names) {
            memcpy(names, ci->ppEnabledExtensionNames, ci->enabledExtensionCount * sizeof(*names));
            names[ci->enabledExtensionCount] = ext;
            ci2.enabledExtensionCount++;
            ci2.ppEnabledExtensionNames = names;
        } else {
            usable = false;
        }
    }
    if (usable && !feat)
        ci2.pNext = &feat2;
    bool compression_control = usable && (!feat || feat->imageCompressionControl);

    VkResult r = create(phys, &ci2, alloc, out);
    free(names);
    if (r != VK_SUCCESS)
        return r;
    if (!compression_control)
        fprintf(stderr, LAYER ": VK_EXT_image_compression_control unavailable, doing nothing\n");

    struct dev *d = calloc(1, sizeof(*d));
    if (!d) {
        ((PFN_vkDestroyDevice)gdpa(*out, "vkDestroyDevice"))(*out, alloc);
        return VK_ERROR_OUT_OF_HOST_MEMORY;
    }
    d->key = KEY(*out);
    d->gdpa = gdpa;
    d->destroy = (PFN_vkDestroyDevice)gdpa(*out, "vkDestroyDevice");
    d->create_image = (PFN_vkCreateImage)gdpa(*out, "vkCreateImage");
    d->compression_control = compression_control;
    pthread_mutex_lock(&lock);
    d->next = devs;
    devs = d;
    pthread_mutex_unlock(&lock);
    return VK_SUCCESS;
}

static VKAPI_ATTR void VKAPI_CALL DestroyDevice(VkDevice device, const VkAllocationCallbacks *alloc)
{
    if (!device)
        return;
    struct dev *d = unlink_key((void **)&devs, KEY(device));
    if (d) {
        d->destroy(device, alloc);
        free(d);
    }
}

static VKAPI_ATTR VkResult VKAPI_CALL CreateImage(VkDevice device, const VkImageCreateInfo *ci,
                                                  const VkAllocationCallbacks *alloc, VkImage *out)
{
    struct dev *d = find_dev(KEY(device));
    const VkExternalMemoryImageCreateInfo *ext =
        find_struct(ci->pNext, VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_IMAGE_CREATE_INFO);
    if (d->compression_control && ext &&
        (ext->handleTypes & VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT) &&
        !find_struct(ci->pNext, VK_STRUCTURE_TYPE_IMAGE_COMPRESSION_CONTROL_EXT)) {
        VkImageCompressionControlEXT cc = {
            .sType = VK_STRUCTURE_TYPE_IMAGE_COMPRESSION_CONTROL_EXT,
            .pNext = ci->pNext,
            .flags = VK_IMAGE_COMPRESSION_DISABLED_EXT,
        };
        VkImageCreateInfo ci2 = *ci;
        ci2.pNext = &cc;
        fprintf(stderr, LAYER ": shared %ux%u image (format %d, usage 0x%x) uncompressed\n",
                ci->extent.width, ci->extent.height, ci->format, ci->usage);
        return d->create_image(device, &ci2, alloc, out);
    }
    return d->create_image(device, ci, alloc, out);
}

static PFN_vkVoidFunction intercept(const char *name);

static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL GetDeviceProcAddr(VkDevice device, const char *name)
{
    PFN_vkVoidFunction f = intercept(name);
    if (f)
        return f;
    struct dev *d = find_dev(KEY(device));
    return d ? d->gdpa(device, name) : NULL;
}

static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL GetInstanceProcAddr(VkInstance instance, const char *name)
{
    if (!strcmp(name, "vkCreateInstance"))
        return (PFN_vkVoidFunction)CreateInstance;
    PFN_vkVoidFunction f = intercept(name);
    if (f || !instance)
        return f;
    if (!strcmp(name, "vkDestroyInstance"))
        return (PFN_vkVoidFunction)DestroyInstance;
    if (!strcmp(name, "vkCreateDevice"))
        return (PFN_vkVoidFunction)CreateDevice;
    struct inst *i = find_inst(KEY(instance));
    return i ? i->gipa(instance, name) : NULL;
}

static PFN_vkVoidFunction intercept(const char *name)
{
    if (!strcmp(name, "vkGetInstanceProcAddr"))
        return (PFN_vkVoidFunction)GetInstanceProcAddr;
    if (!strcmp(name, "vkGetDeviceProcAddr"))
        return (PFN_vkVoidFunction)GetDeviceProcAddr;
    if (!strcmp(name, "vkDestroyDevice"))
        return (PFN_vkVoidFunction)DestroyDevice;
    if (!strcmp(name, "vkCreateImage"))
        return (PFN_vkVoidFunction)CreateImage;
    return NULL;
}

EXPORT VKAPI_ATTR VkResult VKAPI_CALL
vkNegotiateLoaderLayerInterfaceVersion(VkNegotiateLayerInterface *v)
{
    if (v->loaderLayerInterfaceVersion < 2)
        return VK_ERROR_INITIALIZATION_FAILED;
    v->loaderLayerInterfaceVersion = 2;
    v->pfnGetInstanceProcAddr = GetInstanceProcAddr;
    v->pfnGetDeviceProcAddr = GetDeviceProcAddr;
    v->pfnGetPhysicalDeviceProcAddr = NULL;
    return VK_SUCCESS;
}
