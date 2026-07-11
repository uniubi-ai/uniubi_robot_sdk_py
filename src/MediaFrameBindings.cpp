#include "MediaFrameBindings.h"

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include <pybind11/stl.h>

#include "uniubi/robot_sdk/Media/Define.h"
#include "uniubi/robot_sdk/Media/FrameInfo.h"
#include "uniubi/robot_sdk/Media/MediaFrame.h"
#include "uniubi/robot_sdk/Media/MediaBuffer.h"

namespace py = pybind11;

namespace {

using Uface::Media::AudioFrameInfo;
using Uface::Media::AudioFrame;
using Uface::Media::MediaBuffer;
using Uface::Media::MediaBufferMeta;
using Uface::Media::ImuFrameMetaHeader;
using Uface::Media::ImuSample;
using Uface::Media::VideoFrame;
using Uface::Media::VideoFrameInfo;
using Uface::Stream::AFrameInfo;
using Uface::Stream::CMediaFrame;
using Uface::Stream::FrameInfo;
using Uface::Stream::VFrameInfo;

py::bytes bufferToBytes(const MediaBuffer& buffer) {
    const uint32_t size = buffer.size();
    const uint8_t* data = buffer.data();
    if (!data || size == 0) {
        return py::bytes();
    }
    return py::bytes(reinterpret_cast<const char*>(data), size);
}

py::bytes extraToBytes(const MediaBuffer& buffer) {
    const uint32_t size = buffer.extraSize();
    const uint8_t* data = buffer.extraData();
    if (!data || size == 0) {
        return py::bytes();
    }
    return py::bytes(reinterpret_cast<const char*>(data), size);
}

py::bytes metaToBytes(const MediaBufferMeta& meta) {
    if (!meta.data || meta.size == 0) {
        return py::bytes();
    }
    return py::bytes(reinterpret_cast<const char*>(meta.data), meta.size);
}

std::vector<uint32_t> uintArrayToVector(const uint32_t (&values)[3]) {
    return {values[0], values[1], values[2]};
}

void vectorToUintArray(const std::vector<uint32_t>& values, uint32_t (&out)[3]) {
    for (size_t i = 0; i < 3; ++i) {
        out[i] = i < values.size() ? values[i] : 0;
    }
}

void releaseOwnedBytes(void* data, int32_t, void*) {
    delete[] static_cast<uint8_t*>(data);
}

void releaseOwnedPacketBytes(void* data, size_t, uint8_t*) {
    delete[] static_cast<uint8_t*>(data);
}

uint8_t* copyBytes(const py::bytes& data, uint32_t& size) {
    std::string bytes = data;
    size = static_cast<uint32_t>(bytes.size());

    uint8_t* raw = new uint8_t[std::max<uint32_t>(size, 1)];
    if (size > 0) {
        std::memcpy(raw, bytes.data(), size);
    }
    return raw;
}

MediaBuffer makeMediaBuffer(const py::bytes& data, uint32_t extraSize) {
    uint32_t size = 0;
    uint8_t* raw = copyBytes(data, size);
    return MediaBuffer(raw, size, extraSize, Uface::Media::FreeMemoryFunc(&releaseOwnedBytes));
}

VideoFrame makeVideoFrame(const py::bytes& data, const VideoFrameInfo& info, uint32_t extraSize) {
    uint32_t size = 0;
    uint8_t* raw = copyBytes(data, size);
    VideoFrame frame(raw, size, extraSize, Uface::Media::FreeMemoryFunc(&releaseOwnedBytes));
    frame.setFrameInfo(info);
    return frame;
}

AudioFrame makeAudioFrame(const py::bytes& data, const AudioFrameInfo& info, uint32_t extraSize) {
    uint32_t size = 0;
    uint8_t* raw = copyBytes(data, size);
    AudioFrame frame(raw, size, extraSize, Uface::Media::FreeMemoryFunc(&releaseOwnedBytes));
    frame.setFrameInfo(info);
    return frame;
}

CMediaFrame makeEncodedMediaFrame(const py::bytes& data) {
    uint32_t size = 0;
    uint8_t* raw = copyBytes(data, size);
    return CMediaFrame(raw, size, Uface::Memory::FreeMemoryFunc(&releaseOwnedPacketBytes));
}

py::bytes encodedFrameToBytes(const CMediaFrame& frame) {
    const int32_t size = frame.size();
    const uint8_t* data = frame.getBuffer();
    if (!data || size <= 0) {
        return py::bytes();
    }
    return py::bytes(reinterpret_cast<const char*>(data), size);
}

class VideoFrameRowView {
public:
    VideoFrameRowView(uint8_t* data, ssize_t size)
        : mData(data)
        , mSize(size) {
        if (!mData) {
            throw py::value_error("video frame row is null");
        }
        if (mSize < 0) {
            throw py::value_error("video frame row size is invalid");
        }
    }

    ssize_t size() const {
        return mSize;
    }

    py::buffer_info bufferInfo() const {
        return py::buffer_info(
            mData,
            static_cast<ssize_t>(sizeof(uint8_t)),
            py::format_descriptor<uint8_t>::format(),
            1,
            {mSize},
            {static_cast<ssize_t>(sizeof(uint8_t))},
            true);
    }

private:
    uint8_t* mData;
    ssize_t mSize;
};

class VideoFramePlaneView {
public:
    VideoFramePlaneView(VideoFrame frame, int32_t plane)
        : mFrame(std::move(frame))
        , mPlane(plane) {
        init();
    }

    int32_t plane() const {
        return mPlane;
    }

    const std::vector<ssize_t>& shape() const {
        return mShape;
    }

    const std::vector<ssize_t>& strides() const {
        return mStrides;
    }

    ssize_t rows() const {
        return mShape.empty() ? 0 : mShape[0];
    }

    ssize_t rowBytes() const {
        if (mShape.size() == 1) {
            return mItemSize;
        }
        if (mShape.size() == 2) {
            return mShape[1] * mItemSize;
        }
        if (mShape.size() == 3) {
            return mShape[1] * mShape[2] * mItemSize;
        }
        throw py::value_error("unsupported plane_view dimension");
    }

    std::shared_ptr<VideoFrameRowView> rowView(ssize_t row) const {
        if (row < 0 || row >= rows()) {
            throw py::index_error("row index out of range");
        }
        return std::make_shared<VideoFrameRowView>(mData + row * mStrides[0], rowBytes());
    }

    py::buffer_info bufferInfo() const {
        return py::buffer_info(
            mData,
            mItemSize,
            mFormat,
            static_cast<ssize_t>(mShape.size()),
            mShape,
            mStrides,
            true);
    }

private:
    void init() {
        const VideoFrameInfo& info = mFrame.getFrameInfo();
        if (mPlane < 0 || mPlane >= 3) {
            throw py::index_error("plane index out of range");
        }

        const ssize_t width = static_cast<ssize_t>(info.width);
        const ssize_t height = static_cast<ssize_t>(info.height);
        ssize_t stride = static_cast<ssize_t>(info.stride[mPlane]);
        if (stride <= 0) {
            stride = defaultPlaneStride(info);
        }
        if (stride <= 0) {
            throw py::value_error("video frame plane stride is invalid");
        }

        mData = planeAddress(info, height, stride);
        if (!mData) {
            throw py::value_error("video frame plane is null");
        }

        switch (info.pixelFormat) {
            case Uface::Media::mediaPixelFormatNV12:
            case Uface::Media::mediaPixelFormatNV21:
                initYuv420SemiPlanar(width, height, stride);
                break;
            case Uface::Media::mediaPixelFormatNV16:
            case Uface::Media::mediaPixelFormatNV61:
                initYuv422SemiPlanar(width, height, stride);
                break;
            case Uface::Media::mediaPixelFormatYUV420P:
            case Uface::Media::mediaPixelFormatYUV420M:
                initPlanar(width, height, stride, 2, 2);
                break;
            case Uface::Media::mediaPixelFormatYUV422P:
            case Uface::Media::mediaPixelFormatYUV422M:
            case Uface::Media::mediaPixelFormatYUV422RM:
                initPlanar(width, height, stride, 2, 1);
                break;
            case Uface::Media::mediaPixelFormatYUV444P:
            case Uface::Media::mediaPixelFormatYUV444M:
                initPlanar(width, height, stride, 1, 1);
                break;
            case Uface::Media::mediaPixelFormatYUV400:
                requirePlane(0);
                mShape = {height, width};
                mStrides = {stride, 1};
                break;
            case Uface::Media::mediaPixelFormatS16C1:
                requirePlane(0);
                mItemSize = static_cast<ssize_t>(sizeof(int16_t));
                mFormat = py::format_descriptor<int16_t>::format();
                mShape = {height, width};
                mStrides = {stride, mItemSize};
                break;
            case Uface::Media::mediaPixelFormatU16C1:
                requirePlane(0);
                mItemSize = static_cast<ssize_t>(sizeof(uint16_t));
                mFormat = py::format_descriptor<uint16_t>::format();
                mShape = {height, width};
                mStrides = {stride, mItemSize};
                break;
            case Uface::Media::mediaPixelFormatRGB888:
            case Uface::Media::mediaPixelFormatBGR888:
                requirePlane(0);
                mShape = {height, width, 3};
                mStrides = {stride, 3, 1};
                break;
            case Uface::Media::mediaPixelFormatRGBA8888:
            case Uface::Media::mediaPixelFormatBGRA8888:
            case Uface::Media::mediaPixelFormatARGB8888:
            case Uface::Media::mediaPixelFormatABGR8888:
                requirePlane(0);
                mShape = {height, width, 4};
                mStrides = {stride, 4, 1};
                break;
            case Uface::Media::mediaPixelFormatYUYV422:
            case Uface::Media::mediaPixelFormatUYVY422:
                requirePlane(0);
                mShape = {height, width, 2};
                mStrides = {stride, 2, 1};
                break;
            default:
                initFallback(width, height, stride);
                break;
        }
    }

    void requirePlane(int32_t expected) const {
        if (mPlane != expected) {
            throw py::index_error("plane index is invalid for this pixel format");
        }
    }

    void initYuv420SemiPlanar(ssize_t width, ssize_t height, ssize_t stride) {
        if (mPlane == 0) {
            mShape = {height, width};
            mStrides = {stride, 1};
        } else if (mPlane == 1) {
            mShape = {divideRoundUp(height, 2), divideRoundUp(width, 2), 2};
            mStrides = {stride, 2, 1};
        } else {
            throw py::index_error("plane index is invalid for NV12/NV21");
        }
    }

    void initYuv422SemiPlanar(ssize_t width, ssize_t height, ssize_t stride) {
        if (mPlane == 0) {
            mShape = {height, width};
            mStrides = {stride, 1};
        } else if (mPlane == 1) {
            mShape = {height, width / 2, 2};
            mStrides = {stride, 2, 1};
        } else {
            throw py::index_error("plane index is invalid for NV16/NV61");
        }
    }

    void initPlanar(ssize_t width, ssize_t height, ssize_t stride, ssize_t hSubsample, ssize_t vSubsample) {
        if (mPlane == 0) {
            mShape = {height, width};
        } else if (mPlane == 1 || mPlane == 2) {
            mShape = {divideRoundUp(height, vSubsample), divideRoundUp(width, hSubsample)};
        } else {
            throw py::index_error("plane index is invalid for planar YUV");
        }
        mStrides = {stride, 1};
    }

    static ssize_t divideRoundUp(ssize_t value, ssize_t divisor) {
        return (value + divisor - 1) / divisor;
    }

    void initFallback(ssize_t width, ssize_t height, ssize_t stride) {
        requirePlane(0);
        const ssize_t rows = height > 0 ? height : 1;
        const ssize_t cols = width > 0 ? width : static_cast<ssize_t>(mFrame.size());
        mShape = {rows, cols};
        mStrides = {stride, 1};
    }

    ssize_t defaultPlaneStride(const VideoFrameInfo& info) const {
        if (mPlane == 0) {
            return defaultPackedStride(info);
        }

        switch (info.pixelFormat) {
            case Uface::Media::mediaPixelFormatNV12:
            case Uface::Media::mediaPixelFormatNV21:
            case Uface::Media::mediaPixelFormatNV16:
            case Uface::Media::mediaPixelFormatNV61:
                return info.stride[0] > 0 ? static_cast<ssize_t>(info.stride[0])
                                          : static_cast<ssize_t>(info.width);
            case Uface::Media::mediaPixelFormatYUV420P:
            case Uface::Media::mediaPixelFormatYUV420M:
            case Uface::Media::mediaPixelFormatYUV422P:
            case Uface::Media::mediaPixelFormatYUV422M:
            case Uface::Media::mediaPixelFormatYUV422RM:
                return static_cast<ssize_t>(info.width / 2);
            case Uface::Media::mediaPixelFormatYUV444P:
            case Uface::Media::mediaPixelFormatYUV444M:
                return static_cast<ssize_t>(info.width);
            default:
                return 0;
        }
    }

    static ssize_t defaultPackedStride(const VideoFrameInfo& info) {
        switch (info.pixelFormat) {
            case Uface::Media::mediaPixelFormatRGB888:
            case Uface::Media::mediaPixelFormatBGR888:
                return static_cast<ssize_t>(info.width) * 3;
            case Uface::Media::mediaPixelFormatRGBA8888:
            case Uface::Media::mediaPixelFormatBGRA8888:
            case Uface::Media::mediaPixelFormatARGB8888:
            case Uface::Media::mediaPixelFormatABGR8888:
                return static_cast<ssize_t>(info.width) * 4;
            case Uface::Media::mediaPixelFormatYUYV422:
            case Uface::Media::mediaPixelFormatUYVY422:
                return static_cast<ssize_t>(info.width) * 2;
            default:
                return static_cast<ssize_t>(info.width);
        }
    }

    uint8_t* planeAddress(const VideoFrameInfo& info, ssize_t height, ssize_t stride) const {
        uint8_t* data = info.virAddr[mPlane];
        if (data) {
            return data;
        }
        if (mPlane == 0) {
            return mFrame.data();
        }
        if ((info.pixelFormat == Uface::Media::mediaPixelFormatNV12 ||
             info.pixelFormat == Uface::Media::mediaPixelFormatNV21 ||
             info.pixelFormat == Uface::Media::mediaPixelFormatNV16 ||
             info.pixelFormat == Uface::Media::mediaPixelFormatNV61) &&
            mPlane == 1 &&
            mFrame.data()) {
            const ssize_t yStride = info.stride[0] > 0 ? info.stride[0] : stride;
            return mFrame.data() + yStride * height;
        }
        return nullptr;
    }

private:
    VideoFrame mFrame;
    int32_t mPlane;
    uint8_t* mData = nullptr;
    ssize_t mItemSize = static_cast<ssize_t>(sizeof(uint8_t));
    std::string mFormat = py::format_descriptor<uint8_t>::format();
    std::vector<ssize_t> mShape;
    std::vector<ssize_t> mStrides;
};

class MediaBufferView {
public:
    explicit MediaBufferView(MediaBuffer buffer)
        : mBuffer(std::move(buffer)) {
        if (!mBuffer.valid() || mBuffer.data() == nullptr) {
            throw py::value_error("media buffer is invalid");
        }
    }

    uint32_t size() const {
        return mBuffer.size();
    }

    py::buffer_info bufferInfo() const {
        return py::buffer_info(
            mBuffer.data(),
            static_cast<ssize_t>(sizeof(uint8_t)),
            py::format_descriptor<uint8_t>::format(),
            1,
            {static_cast<ssize_t>(mBuffer.size())},
            {static_cast<ssize_t>(sizeof(uint8_t))},
            true);
    }

private:
    MediaBuffer mBuffer;
};

class CMediaFrameView {
public:
    explicit CMediaFrameView(CMediaFrame frame)
        : mFrame(std::move(frame)) {
        if (!mFrame.valid() || !mFrame.getBuffer()) {
            throw py::value_error("encoded media frame is invalid");
        }
    }

    int32_t size() const {
        return mFrame.size();
    }

    py::buffer_info bufferInfo() const {
        return py::buffer_info(
            mFrame.getBuffer(),
            static_cast<ssize_t>(sizeof(uint8_t)),
            py::format_descriptor<uint8_t>::format(),
            1,
            {static_cast<ssize_t>(mFrame.size())},
            {static_cast<ssize_t>(sizeof(uint8_t))},
            true);
    }

private:
    CMediaFrame mFrame;
};

template <class T>
int u8ToInt(const T& value) {
    return static_cast<int>(value);
}

struct MetadataTlvHeader {
    uint32_t magic;
    uint16_t version;
    uint16_t count;
    uint32_t size;
};

struct MetadataTlvItem {
    uint32_t type;
    uint32_t size;
};

constexpr uint32_t kMetadataTlvMagic = (('M' << 24) | ('T' << 16) | ('L' << 8) | 'V');
constexpr uint16_t kMetadataTlvVersion = 1;

uint32_t alignedMetadataSize(uint32_t size) {
    return (size + 3u) & ~3u;
}

py::bytes bytesFromSpan(const uint8_t* data, uint32_t size) {
    if (!data || size == 0) {
        return py::bytes();
    }
    return py::bytes(reinterpret_cast<const char*>(data), size);
}

void validateMetadataTlv(const MediaBufferMeta& meta) {
    if (!meta.data || meta.size == 0) {
        return;
    }
    if (meta.type != Uface::Media::mediaBufferMetaTLV || meta.size < sizeof(MetadataTlvHeader)) {
        throw py::value_error("invalid media buffer metadata tlv");
    }

    const auto* header = reinterpret_cast<const MetadataTlvHeader*>(meta.data);
    if (header->magic != kMetadataTlvMagic ||
        header->version != kMetadataTlvVersion ||
        header->size != meta.size) {
        throw py::value_error("invalid media buffer metadata tlv header");
    }

    uint32_t offset = static_cast<uint32_t>(sizeof(MetadataTlvHeader));
    for (uint16_t i = 0; i < header->count; ++i) {
        if (offset > meta.size || sizeof(MetadataTlvItem) > meta.size - offset) {
            throw py::value_error("invalid media buffer metadata tlv item");
        }

        const auto* item = reinterpret_cast<const MetadataTlvItem*>(meta.data + offset);
        if (item->type == Uface::Media::mediaBufferMetaUnknown) {
            throw py::value_error("invalid media buffer metadata type");
        }

        offset += static_cast<uint32_t>(sizeof(MetadataTlvItem));
        if (item->size > meta.size - offset) {
            throw py::value_error("invalid media buffer metadata size");
        }

        const uint32_t alignedSize = alignedMetadataSize(item->size);
        if (alignedSize > meta.size - offset) {
            throw py::value_error("invalid media buffer metadata alignment");
        }
        offset += alignedSize;
    }

    if (offset != meta.size) {
        throw py::value_error("invalid media buffer metadata tlv size");
    }
}

py::list metadataItemsToPy(const MediaBuffer& buffer) {
    const MediaBufferMeta meta = buffer.metaData();
    py::list result;
    if (!meta.data || meta.size == 0) {
        return result;
    }

    validateMetadataTlv(meta);

    const auto* header = reinterpret_cast<const MetadataTlvHeader*>(meta.data);
    uint32_t offset = static_cast<uint32_t>(sizeof(MetadataTlvHeader));
    for (uint16_t i = 0; i < header->count; ++i) {
        const auto* item = reinterpret_cast<const MetadataTlvItem*>(meta.data + offset);
        const uint8_t* data = meta.data + offset + sizeof(MetadataTlvItem);
        result.append(py::make_tuple(item->type, bytesFromSpan(data, item->size)));
        offset += static_cast<uint32_t>(sizeof(MetadataTlvItem)) + alignedMetadataSize(item->size);
    }
    return result;
}

py::dict metadataDictToPy(const MediaBuffer& buffer) {
    const MediaBufferMeta meta = buffer.metaData();
    py::dict result;
    if (!meta.data || meta.size == 0) {
        return result;
    }

    validateMetadataTlv(meta);

    const auto* header = reinterpret_cast<const MetadataTlvHeader*>(meta.data);
    uint32_t offset = static_cast<uint32_t>(sizeof(MetadataTlvHeader));
    for (uint16_t i = 0; i < header->count; ++i) {
        const auto* item = reinterpret_cast<const MetadataTlvItem*>(meta.data + offset);
        const uint8_t* data = meta.data + offset + sizeof(MetadataTlvItem);
        result[py::int_(item->type)] = bytesFromSpan(data, item->size);
        offset += static_cast<uint32_t>(sizeof(MetadataTlvItem)) + alignedMetadataSize(item->size);
    }
    return result;
}

py::dict imuSampleToPy(const ImuSample& sample) {
    py::dict result;
    result["pts_us"] = py::int_(sample.ptsUs);
    result["x"] = py::int_(sample.x);
    result["y"] = py::int_(sample.y);
    result["z"] = py::int_(sample.z);
    result["temperature"] = py::int_(sample.temperature);
    return result;
}

void validateImuSampleRange(const ImuFrameMetaHeader& header,
                            uint32_t offset,
                            uint32_t count,
                            const char* name) {
    if (count == 0) {
        return;
    }
    if (offset < header.headerSize || offset > header.totalSize) {
        throw py::value_error(std::string("invalid IMU metadata ") + name + " offset");
    }

    const uint64_t sampleBytes = static_cast<uint64_t>(count) * sizeof(ImuSample);
    if (sampleBytes > static_cast<uint64_t>(header.totalSize - offset)) {
        throw py::value_error(std::string("invalid IMU metadata ") + name + " size");
    }
}

py::list imuSamplesToPy(const uint8_t* data, uint32_t offset, uint32_t count) {
    py::list samples;
    for (uint32_t i = 0; i < count; ++i) {
        ImuSample sample;
        std::memcpy(&sample, data + offset + static_cast<uint64_t>(i) * sizeof(ImuSample), sizeof(sample));
        samples.append(imuSampleToPy(sample));
    }
    return samples;
}

py::object imuMetadataToPy(const MediaBuffer& buffer) {
    MediaBufferMeta meta;
    if (!buffer.getMetaData(Uface::Media::mediaBufferMetaIMU, meta)) {
        return py::none();
    }
    if (!meta.data || meta.size < sizeof(ImuFrameMetaHeader)) {
        throw py::value_error("invalid IMU metadata header");
    }

    ImuFrameMetaHeader header;
    std::memcpy(&header, meta.data, sizeof(header));

    if (header.headerSize < sizeof(ImuFrameMetaHeader) ||
        header.headerSize > header.totalSize ||
        header.totalSize != meta.size) {
        throw py::value_error("invalid IMU metadata size");
    }

    validateImuSampleRange(header, header.gyroOffset, header.gyroCount, "gyro");
    validateImuSampleRange(header, header.accOffset, header.accCount, "acc");

    py::list rotation;
    for (int value : header.rotation) {
        rotation.append(value);
    }

    py::dict result;
    result["header_size"] = py::int_(header.headerSize);
    result["total_size"] = py::int_(header.totalSize);
    result["frame_pts_us"] = py::int_(header.framePtsUs);
    result["window_begin_us"] = py::int_(header.windowBeginUs);
    result["window_end_us"] = py::int_(header.windowEndUs);
    result["gyro_count"] = py::int_(header.gyroCount);
    result["acc_count"] = py::int_(header.accCount);
    result["gyro_offset"] = py::int_(header.gyroOffset);
    result["acc_offset"] = py::int_(header.accOffset);
    result["coord_frame"] = py::int_(static_cast<int32_t>(header.coordFrame));
    result["status"] = py::int_(static_cast<int32_t>(header.status));
    result["rotation"] = rotation;
    result["gyro"] = imuSamplesToPy(meta.data, header.gyroOffset, header.gyroCount);
    result["acc"] = imuSamplesToPy(meta.data, header.accOffset, header.accCount);
    return result;
}

}


void bindMediaFrameTypes(py::module_& m) {
    /// ───────────────────────────────────────────────────────
    /// MediaBus 帧格式（Motion SDK 自带导出，不依赖 uniubi_mediabus 包）
    /// ───────────────────────────────────────────────────────
    m.attr("FIRST_PKT") = py::int_(FIRST_PKT);
    m.attr("LAST_PKT") = py::int_(LAST_PKT);
    m.attr("IMU_FRAME_META_HEADER_SIZE") = py::int_(sizeof(ImuFrameMetaHeader));
    m.attr("IMU_SAMPLE_SIZE") = py::int_(sizeof(ImuSample));

    py::enum_<Uface::Media::MediaPixelFormat>(m, "MediaPixelFormat")
        .value("mediaPixelFormatUnknown", Uface::Media::mediaPixelFormatUnknown)
        .value("mediaPixelFormatNV12", Uface::Media::mediaPixelFormatNV12)
        .value("mediaPixelFormatNV21", Uface::Media::mediaPixelFormatNV21)
        .value("mediaPixelFormatNV16", Uface::Media::mediaPixelFormatNV16)
        .value("mediaPixelFormatNV61", Uface::Media::mediaPixelFormatNV61)
        .value("mediaPixelFormatRGB888", Uface::Media::mediaPixelFormatRGB888)
        .value("mediaPixelFormatBGR888", Uface::Media::mediaPixelFormatBGR888)
        .value("mediaPixelFormatARGB8888", Uface::Media::mediaPixelFormatARGB8888)
        .value("mediaPixelFormatABGR8888", Uface::Media::mediaPixelFormatABGR8888)
        .value("mediaPixelFormatARGB1555", Uface::Media::mediaPixelFormatARGB1555)
        .value("mediaPixelFormatABGR1555", Uface::Media::mediaPixelFormatABGR1555)
        .value("mediaPixelFormatYUYV422", Uface::Media::mediaPixelFormatYUYV422)
        .value("mediaPixelFormatUYVY422", Uface::Media::mediaPixelFormatUYVY422)
        .value("mediaPixelFormatYUV420P", Uface::Media::mediaPixelFormatYUV420P)
        .value("mediaPixelFormatYUV422P", Uface::Media::mediaPixelFormatYUV422P)
        .value("mediaPixelFormatYUV444P", Uface::Media::mediaPixelFormatYUV444P)
        .value("mediaPixelFormatYUV400", Uface::Media::mediaPixelFormatYUV400)
        .value("mediaPixelFormatYUV420M", Uface::Media::mediaPixelFormatYUV420M)
        .value("mediaPixelFormatYUV422RM", Uface::Media::mediaPixelFormatYUV422RM)
        .value("mediaPixelFormatYUV422M", Uface::Media::mediaPixelFormatYUV422M)
        .value("mediaPixelFormatYUV444M", Uface::Media::mediaPixelFormatYUV444M)
        .value("mediaPixelFormatRGBA8888", Uface::Media::mediaPixelFormatRGBA8888)
        .value("mediaPixelFormatBGRA8888", Uface::Media::mediaPixelFormatBGRA8888)
        .value("mediaPixelFormatRGB565", Uface::Media::mediaPixelFormatRGB565)
        .value("mediaPixelFormatRGB888Planar", Uface::Media::mediaPixelFormatRGB888Planar)
        .value("mediaPixelFormatBGR888Planar", Uface::Media::mediaPixelFormatBGR888Planar)
        .value("mediaPixelFormatS16C1", Uface::Media::mediaPixelFormatS16C1)
        .value("mediaPixelFormatU16C1", Uface::Media::mediaPixelFormatU16C1);

    py::enum_<Uface::Media::VideoStreamType>(m, "VideoStreamType")
        .value("videoStreamRGB", Uface::Media::videoStreamRGB)
        .value("videoStreamIR", Uface::Media::videoStreamIR)
        .value("videoStreamDepth", Uface::Media::videoStreamDepth)
        .value("videoStreamDisparity", Uface::Media::videoStreamDisparity)
        .value("videoStreamConfidence", Uface::Media::videoStreamConfidence)
        .value("videoStreamNone", Uface::Media::videoStreamNone);

    py::enum_<Uface::Media::VideoEncode>(m, "VideoEncode")
        .value("vInvalidCodec", Uface::Media::vInvalidCodec)
        .value("videoH264", Uface::Media::videoH264)
        .value("videoH265", Uface::Media::videoH265)
        .value("videoMpeg4", Uface::Media::videoMpeg4)
        .value("videoMJpeg", Uface::Media::videoMJpeg)
        .value("videoJpeg", Uface::Media::videoJpeg)
        .value("videoCodecButt", Uface::Media::videoCodecButt);

    py::enum_<Uface::Media::AudioEncode>(m, "AudioEncode")
        .value("audioAAC", Uface::Media::audioAAC)
        .value("audioG711a", Uface::Media::audioG711a)
        .value("audioG711u", Uface::Media::audioG711u)
        .value("audioG726", Uface::Media::audioG726)
        .value("audioPCM", Uface::Media::audioPCM)
        .value("audioMP3", Uface::Media::audioMP3)
        .value("audioOpus", Uface::Media::audioOpus)
        .value("audioButt", Uface::Media::audioButt);

    py::enum_<Uface::Media::MediaBufferMetaType>(m, "MediaBufferMetaType")
        .value("mediaBufferMetaUnknown", Uface::Media::mediaBufferMetaUnknown)
        .value("mediaBufferMetaTLV", Uface::Media::mediaBufferMetaTLV)
        .value("mediaBufferMetaIMU", Uface::Media::mediaBufferMetaIMU);

    py::enum_<Uface::Media::ImuCoordFrame>(m, "ImuCoordFrame")
        .value("imuCoordUnknown", Uface::Media::imuCoordUnknown)
        .value("imuCoordSensor", Uface::Media::imuCoordSensor)
        .value("imuCoordCamera", Uface::Media::imuCoordCamera)
        .value("imuCoordBody", Uface::Media::imuCoordBody);

    py::enum_<Uface::Media::ImuFrameStatus>(m, "ImuFrameStatus")
        .value("imuFrameStatusOK", Uface::Media::imuFrameStatusOK)
        .value("imuFrameStatusGyroEmpty", Uface::Media::imuFrameStatusGyroEmpty)
        .value("imuFrameStatusAccEmpty", Uface::Media::imuFrameStatusAccEmpty)
        .value("imuFrameStatusGyroDelayed", Uface::Media::imuFrameStatusGyroDelayed)
        .value("imuFrameStatusAccDelayed", Uface::Media::imuFrameStatusAccDelayed)
        .value("imuFrameStatusTimeInvalid", Uface::Media::imuFrameStatusTimeInvalid)
        .value("imuFrameStatusReadFailed", Uface::Media::imuFrameStatusReadFailed)
        .value("imuFrameStatusMetaTooLarge", Uface::Media::imuFrameStatusMetaTooLarge);

    py::enum_<Uface::Stream::StreamType>(m, "StreamType")
        .value("main", Uface::Stream::main)
        .value("extra1", Uface::Stream::extra1)
        .value("extra2", Uface::Stream::extra2)
        .value("extra3", Uface::Stream::extra3)
        .value("snapshot", Uface::Stream::snapshot)
        .value("talkback", Uface::Stream::talkback)
        .value("tapeIn", Uface::Stream::tapeIn)
        .value("streamNumber", Uface::Stream::streamNumber);

    py::enum_<Uface::Stream::StreamTrack>(m, "StreamTrack")
        .value("videoTrack", Uface::Stream::videoTrack)
        .value("audioTrack", Uface::Stream::audioTrack);

    py::enum_<Uface::Stream::FrameType>(m, "FrameType")
        .value("audioFrame", Uface::Stream::audioFrame)
        .value("videoFrame", Uface::Stream::videoFrame)
        .value("auxFrame", Uface::Stream::auxFrame)
        .value("imageFrame", Uface::Stream::imageFrame)
        .value("videoBFrame", Uface::Stream::videoBFrame)
        .value("videoIFrame", Uface::Stream::videoIFrame)
        .value("videoPFrame", Uface::Stream::videoPFrame)
        .value("waterFrame", Uface::Stream::waterFrame)
        .value("auxMetaFrame", Uface::Stream::auxMetaFrame);

    py::enum_<Uface::Stream::StreamChange>(m, "StreamChange")
        .value("streamNoChange", Uface::Stream::streamNoChange)
        .value("streamContentChange", Uface::Stream::streamContentChange)
        .value("streamEncodeChange", Uface::Stream::streamEncodeChange)
        .value("streamOtherChange", Uface::Stream::streamOtherChange);

    py::class_<VFrameInfo>(m, "EncodedVideoFrameInfo")
        .def(py::init<>())
        .def_property("stream",
            [](const VFrameInfo& info) { return u8ToInt(info.stream); },
            [](VFrameInfo& info, int value) { info.stream = static_cast<uint8_t>(value); })
        .def_property("encode",
            [](const VFrameInfo& info) { return u8ToInt(info.encode); },
            [](VFrameInfo& info, int value) { info.encode = static_cast<uint8_t>(value); })
        .def_property("type",
            [](const VFrameInfo& info) { return u8ToInt(info.type); },
            [](VFrameInfo& info, int value) { info.type = static_cast<uint8_t>(value); })
        .def_property("fps_num",
            [](const VFrameInfo& info) { return u8ToInt(info.fpsNum); },
            [](VFrameInfo& info, int value) { info.fpsNum = static_cast<uint8_t>(value); })
        .def_property("fps_den",
            [](const VFrameInfo& info) { return u8ToInt(info.fpsDen); },
            [](VFrameInfo& info, int value) { info.fpsDen = static_cast<uint8_t>(value); })
        .def_readwrite("width", &VFrameInfo::width)
        .def_readwrite("height", &VFrameInfo::height);

    py::class_<AFrameInfo>(m, "EncodedAudioFrameInfo")
        .def(py::init<>())
        .def_property("encode",
            [](const AFrameInfo& info) { return u8ToInt(info.encode); },
            [](AFrameInfo& info, int value) { info.encode = static_cast<uint8_t>(value); })
        .def_property("sample_bit",
            [](const AFrameInfo& info) { return u8ToInt(info.sampleBit); },
            [](AFrameInfo& info, int value) { info.sampleBit = static_cast<uint8_t>(value); })
        .def_property("rate",
            [](const AFrameInfo& info) { return u8ToInt(info.rate); },
            [](AFrameInfo& info, int value) { info.rate = static_cast<uint8_t>(value); })
        .def_property("channel",
            [](const AFrameInfo& info) { return u8ToInt(info.channel); },
            [](AFrameInfo& info, int value) { info.channel = static_cast<uint8_t>(value); });

    py::class_<FrameInfo>(m, "EncodedFrameInfo")
        .def(py::init<>())
        .def_property("type",
            [](const FrameInfo& info) { return static_cast<int>(info.type); },
            [](FrameInfo& info, int value) { info.type = static_cast<int8_t>(value); })
        .def_property("channel",
            [](const FrameInfo& info) { return static_cast<int>(info.channel); },
            [](FrameInfo& info, int value) { info.channel = static_cast<int8_t>(value); })
        .def_property("encrypt",
            [](const FrameInfo& info) { return u8ToInt(info.encrypt); },
            [](FrameInfo& info, int value) { info.encrypt = static_cast<uint8_t>(value); })
        .def_property("change",
            [](const FrameInfo& info) { return u8ToInt(info.change); },
            [](FrameInfo& info, int value) { info.change = static_cast<uint8_t>(value); })
        .def_readwrite("utcms", &FrameInfo::utcms)
        .def_readwrite("sequence", &FrameInfo::seq)
        .def_readwrite("utc", &FrameInfo::utc)
        .def_readwrite("length", &FrameInfo::length)
        .def_readwrite("pts", &FrameInfo::pts)
        .def_readwrite("pts_net", &FrameInfo::ptsNet)
        .def_property("video_info",
            [](const FrameInfo& info) { return info.detail.video; },
            [](FrameInfo& info, const VFrameInfo& value) { info.detail.video = value; })
        .def_property("audio_info",
            [](const FrameInfo& info) { return info.detail.audio; },
            [](FrameInfo& info, const AFrameInfo& value) { info.detail.audio = value; });

    py::class_<VideoFrameInfo>(m, "VideoFrameInfo")
        .def(py::init<>())
        .def_readwrite("width", &VideoFrameInfo::width)
        .def_readwrite("height", &VideoFrameInfo::height)
        .def_readwrite("cap_chan", &VideoFrameInfo::capChan)
        .def_readwrite("stream", &VideoFrameInfo::stream)
        .def_readwrite("pixel_format", &VideoFrameInfo::pixelFormat)
        .def_readwrite("timestamp", &VideoFrameInfo::timestamp)
        .def_readwrite("sequence", &VideoFrameInfo::sequence)
        .def_readwrite("memory_fd", &VideoFrameInfo::memoryFd)
        .def_property("stride",
            [](const VideoFrameInfo& info) { return uintArrayToVector(info.stride); },
            [](VideoFrameInfo& info, const std::vector<uint32_t>& values) { vectorToUintArray(values, info.stride); })
        .def_property("stride_v",
            [](const VideoFrameInfo& info) { return uintArrayToVector(info.strideV); },
            [](VideoFrameInfo& info, const std::vector<uint32_t>& values) { vectorToUintArray(values, info.strideV); })
        .def_property_readonly("vir_addr", [](const VideoFrameInfo& info) {
            return std::vector<uint64_t>{
                static_cast<uint64_t>(reinterpret_cast<uintptr_t>(info.virAddr[0])),
                static_cast<uint64_t>(reinterpret_cast<uintptr_t>(info.virAddr[1])),
                static_cast<uint64_t>(reinterpret_cast<uintptr_t>(info.virAddr[2])),
            };
        })
        .def_property_readonly("phy_addr", [](const VideoFrameInfo& info) {
            return std::vector<uint64_t>{
                static_cast<uint64_t>(reinterpret_cast<uintptr_t>(info.phyAddr[0])),
                static_cast<uint64_t>(reinterpret_cast<uintptr_t>(info.phyAddr[1])),
                static_cast<uint64_t>(reinterpret_cast<uintptr_t>(info.phyAddr[2])),
            };
        })
        .def_readwrite("rotate", &VideoFrameInfo::rotate);

    py::class_<AudioFrameInfo>(m, "AudioFrameInfo")
        .def(py::init<>())
        .def_readwrite("sample_rate", &AudioFrameInfo::sampleRate)
        .def_readwrite("sample_format", &AudioFrameInfo::sampleFormat)
        .def_readwrite("channel_count", &AudioFrameInfo::channelCount)
        .def_readwrite("data_type", &AudioFrameInfo::dataType)
        .def_readwrite("loop_times", &AudioFrameInfo::loopTimes)
        .def_readwrite("memory_fd", &AudioFrameInfo::memoryFd)
        .def_readwrite("timestamp", &AudioFrameInfo::timestamp)
        .def_readwrite("sequence", &AudioFrameInfo::sequence)
        .def_readwrite("device", &AudioFrameInfo::device)
        .def_readwrite("channel", &AudioFrameInfo::channel);

    py::class_<VideoFrameRowView, std::shared_ptr<VideoFrameRowView>>(m, "VideoFrameRowView", py::buffer_protocol())
        .def_property_readonly("size", &VideoFrameRowView::size)
        .def_buffer(&VideoFrameRowView::bufferInfo);

    py::class_<VideoFramePlaneView, std::shared_ptr<VideoFramePlaneView>>(m, "VideoFramePlaneView", py::buffer_protocol())
        .def_property_readonly("plane", &VideoFramePlaneView::plane)
        .def_property_readonly("shape", [](const VideoFramePlaneView& view) { return view.shape(); })
        .def_property_readonly("strides", [](const VideoFramePlaneView& view) { return view.strides(); })
        .def_property_readonly("rows", &VideoFramePlaneView::rows)
        .def_property_readonly("row_bytes", &VideoFramePlaneView::rowBytes)
        .def("row_view", &VideoFramePlaneView::rowView, py::arg("row"), py::keep_alive<0, 1>())
        .def_buffer(&VideoFramePlaneView::bufferInfo);

    py::class_<MediaBufferView, std::shared_ptr<MediaBufferView>>(m, "MediaBufferView", py::buffer_protocol())
        .def("size", &MediaBufferView::size)
        .def_buffer(&MediaBufferView::bufferInfo);

    py::class_<CMediaFrameView, std::shared_ptr<CMediaFrameView>>(m, "CMediaFrameView", py::buffer_protocol())
        .def("size", &CMediaFrameView::size)
        .def_buffer(&CMediaFrameView::bufferInfo);

    py::class_<CMediaFrame>(m, "CMediaFrame")
        .def(py::init<>())
        .def(py::init<uint32_t>(), py::arg("capacity"))
        .def(py::init(&makeEncodedMediaFrame), py::arg("data"))
        .def("valid", &CMediaFrame::valid)
        .def("reset", &CMediaFrame::reset)
        .def("size", &CMediaFrame::size)
        .def("capacity", &CMediaFrame::capacity)
        .def("data", &encodedFrameToBytes)
        .def("view", [](const CMediaFrame& self) {
            return std::make_shared<CMediaFrameView>(self);
        })
        .def("resize", &CMediaFrame::resize, py::arg("size"))
        .def_property("channel", &CMediaFrame::getChannel, &CMediaFrame::setChannel)
        .def_property("type",
            [](const CMediaFrame& frame) { return static_cast<int>(frame.getType()); },
            [](CMediaFrame& frame, int value) { frame.setType(static_cast<uint8_t>(value)); })
        .def_property("frame_type",
            [](const CMediaFrame& frame) { return static_cast<int>(frame.getFrameType()); },
            [](CMediaFrame& frame, int value) { frame.setFrameType(static_cast<uint8_t>(value)); })
        .def_property("pts", &CMediaFrame::getPts, &CMediaFrame::setPts)
        .def_property("utc", &CMediaFrame::getUtc, &CMediaFrame::setUtc)
        .def_property("sequence", &CMediaFrame::getSequence, &CMediaFrame::setSequence)
        .def_property("new_format", &CMediaFrame::getNewFormat, &CMediaFrame::setNewFormat)
        .def_property("frame_info",
            [](CMediaFrame& frame) -> py::object {
                FrameInfo* info = frame.getFrameInfo();
                if (info == nullptr) {
                    return py::none();
                }
                return py::cast(*info);
            },
            [](CMediaFrame& frame, const FrameInfo& info) { frame.setFrameInfo(&info); })
        .def_property("video_info",
            [](CMediaFrame& frame) -> py::object {
                VFrameInfo info = {};
                if (!frame.getVideoInfo(info)) {
                    return py::none();
                }
                return py::cast(info);
            },
            [](CMediaFrame& frame, const VFrameInfo& info) { frame.setVideoInfo(info); })
        .def_property("audio_info",
            [](CMediaFrame& frame) -> py::object {
                AFrameInfo info = {};
                if (!frame.getAudioInfo(info)) {
                    return py::none();
                }
                return py::cast(info);
            },
            [](CMediaFrame& frame, const AFrameInfo& info) { frame.setAudioInfo(info); });

    py::class_<MediaBuffer>(m, "MediaBuffer")
        .def(py::init<>())
        .def(py::init(&makeMediaBuffer), py::arg("data"), py::arg("extra_size") = 0)
        .def("valid", &MediaBuffer::valid)
        .def("reset", &MediaBuffer::reset)
        .def("size", &MediaBuffer::size)
        .def("extra_size", &MediaBuffer::extraSize)
        .def("data", &bufferToBytes)
        .def("extra_data", &extraToBytes)
        .def("view", [](const MediaBuffer& self) {
            return std::make_shared<MediaBufferView>(self);
        })
        .def("set_size", &MediaBuffer::setSize, py::arg("size"))
        .def("get_fd", &MediaBuffer::getFd)
        .def("set_fd", &MediaBuffer::setFd, py::arg("fd"))
        .def("metadata", [](const MediaBuffer& self) { return metaToBytes(self.metaData()); })
        .def("get_metadata", [](const MediaBuffer& self, uint32_t type) -> py::object {
            MediaBufferMeta meta;
            if (!self.getMetaData(type, meta)) {
                return py::none();
            }
            return metaToBytes(meta);
        }, py::arg("type"))
        .def("has_metadata", [](const MediaBuffer& self, uint32_t type) {
            MediaBufferMeta meta;
            return self.getMetaData(type, meta);
        }, py::arg("type"))
        .def("metadata_items", &metadataItemsToPy)
        .def("metadata_dict", &metadataDictToPy)
        .def("get_imu_metadata", &imuMetadataToPy)
        .def("set_metadata", [](MediaBuffer& self, uint32_t type, const py::bytes& data) {
            std::string bytes = data;
            return self.setMetaData(type, bytes.data(), static_cast<uint32_t>(bytes.size()));
        }, py::arg("type"), py::arg("data"))
        .def("remove_metadata", &MediaBuffer::removeMetaData, py::arg("type"))
        .def("clear_metadata", &MediaBuffer::clearMetaData)
        .def("copy_metadata", &MediaBuffer::copyMetaData, py::arg("other"));

    py::class_<VideoFrame, MediaBuffer>(m, "VideoFrame")
        .def(py::init<>())
        .def(py::init(&makeVideoFrame), py::arg("data"), py::arg("info") = VideoFrameInfo(), py::arg("extra_size") = 0)
        .def("plane_view", [](const VideoFrame& frame, int32_t plane) {
            return std::make_shared<VideoFramePlaneView>(frame, plane);
        }, py::arg("plane"))
        .def_property("frame_info",
            [](const VideoFrame& frame) { return frame.getFrameInfo(); },
            [](VideoFrame& frame, const VideoFrameInfo& info) { frame.setFrameInfo(info); });

    py::class_<AudioFrame, MediaBuffer>(m, "AudioFrame")
        .def(py::init<>())
        .def(py::init(&makeAudioFrame), py::arg("data"), py::arg("info") = AudioFrameInfo(), py::arg("extra_size") = 0)
        .def_property("frame_info",
            [](const AudioFrame& frame) { return frame.getFrameInfo(); },
            [](AudioFrame& frame, const AudioFrameInfo& info) { frame.setFrameInfo(info); });

}
