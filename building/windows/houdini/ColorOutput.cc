// SPDX-License-Identifier: Apache-2.0
// A thin Houdini image-device adapter. Husk serializes USD float arrays as
// strings; restore the EXR chromaticities type before the stock OIIO writer.
#include <IMG/IMG_File.h>
#include <IMG/IMG_FileParms.h>
#include <IMG/IMG_Format.h>
#include <IMG/IMG_Stat.h>
#include <UT/UT_JSONValue.h>
#include <cmath>
#include <mutex>
#include <sstream>

namespace {
const IMG_Format* writer() { return IMG_Format::findFormatByName("oiio"); }

class ColorFile final : public IMG_File {
    IMG_FilePtr mOutput;
public:
    ~ColorFile() override { close(); }
    int readScanline(int, void*) override { return 0; }
    int createFile(const char* filename, const IMG_Stat& stat) override {
        myStat = stat;
        // Metadata supplied as file options is already in myStat at this point.
        UT_StringHolder text;
        if (!myStat.metadata().toString("moonray_chromaticities", text, "OpenEXR", false)) return 0;
        std::string numbers(text.c_str());
        for (char& c : numbers) if (c == '[' || c == ']' || c == ',') c = ' ';
        std::istringstream stream(numbers);
        UT_JSONValue values;
        values.startArray();
        for (int i = 0; i != 8; ++i) {
            double value;
            if (!(stream >> value) || !std::isfinite(value)) return 0;
            values.appendArray(UT_JSONValue(value));
        }
        myStat.metadata().erase("OpenEXR:chromaticities");
        myStat.metadata().erase("chromaticities");
        myStat.metadata().add("chromaticities", IMG_MetadataItem(values, IMG_Metadata::Storage::MD_Real32));
        myStat.setMetadataKey("OpenEXR");
        IMG_FileParms options;
        options.readAsIs();
        mOutput = IMG_File::create(filename, myStat, &options, writer());
        return mOutput ? 1 : 0;
    }
    int writeScanline(int y, const void* data) override { return mOutput && mOutput->write(y, data); }
    int writePlaneScanline(const void* data, int y, const IMG_Plane& plane) override {
        return mOutput && mOutput->write(y, data, &plane);
    }
    int closeFile() override {
        if (!mOutput) return 1;
        const int result = mOutput->close();
        mOutput.reset();
        return result;
    }
};

class ColorFormat final : public IMG_Format {
public:
    const char* getFormatName() const override { return "MoonRayEXR"; }
    const char* getFormatLabel() const override { return "MoonRay Color-managed OpenEXR"; }
    const char* getMetadataKey() const override { return "OpenEXR"; }
    const char* getDefaultExtension() const override { return "exr"; }
    // Explicit opt-in only. Never intercept other renderers' .exr output.
    int checkExtension(const char*) const override { return 0; }
    bool isReadable() const override { return false; }
    bool isWritable() const override { return true; }
    IMG_File* createFile() const override { return new ColorFile; }
    IMG_DataType getSupportedTypes() const override { return writer()->getSupportedTypes(); }
    IMG_ColorModel getSupportedColorModels() const override { return writer()->getSupportedColorModels(); }
    void getMaxResolution(unsigned& x, unsigned& y) const override { writer()->getMaxResolution(x,y); }
    int isWriteRandomAccess() const override { return writer()->isWriteRandomAccess(); }
    int isTopFirst() const override { return writer()->isTopFirst(); }
    int isLeftFirst() const override { return writer()->isLeftFirst(); }
    bool isDataWindowSupported() const override { return writer()->isDataWindowSupported(); }
    bool isDataWindowCropOnly() const override { return writer()->isDataWindowCropOnly(); }
    bool isDeepRasterSupported() const override { return writer()->isDeepRasterSupported(); }
    IMG_DeepRasterColor getDeepRasterRGBASupport() const override { return writer()->getDeepRasterRGBASupport(); }
    bool isDataInterleaved() const override { return writer()->isDataInterleaved(); }
    bool canPlaneTypesDiffer() const override { return writer()->canPlaneTypesDiffer(); }
    bool formatStoresColorSpace() const override { return true; }
    const IMG_MetadataOptions& formatMetadata() const override { return writer()->formatMetadata(); }
};
}

namespace hdMoonray {
void registerColorOutput() {
    static std::once_flag registered;
    std::call_once(registered, [] { if (writer()) new ColorFormat; });
}
}
