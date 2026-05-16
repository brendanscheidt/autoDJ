#include "sha256.hpp"

#include <algorithm>
#include <cstring>
#include <iomanip>
#include <sstream>

namespace autodj::repository::detail {
namespace {

constexpr std::array<std::uint32_t, 64> kRoundConstants{
    0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U, 0x3956c25bU, 0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U,
    0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U, 0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U, 0xc19bf174U,
    0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU, 0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU,
    0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U, 0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U,
    0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU, 0x53380d13U, 0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
    0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U, 0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U,
    0x19a4c116U, 0x1e376c08U, 0x2748774cU, 0x34b0bcb5U, 0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
    0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U, 0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U,
};

std::uint32_t rotateRight(std::uint32_t value, int amount) {
    return (value >> amount) | (value << (32 - amount));
}

std::uint32_t readBigEndian32(const std::uint8_t* bytes) {
    return (static_cast<std::uint32_t>(bytes[0]) << 24) | (static_cast<std::uint32_t>(bytes[1]) << 16)
           | (static_cast<std::uint32_t>(bytes[2]) << 8) | static_cast<std::uint32_t>(bytes[3]);
}

void writeBigEndian32(std::uint32_t value, std::uint8_t* bytes) {
    bytes[0] = static_cast<std::uint8_t>((value >> 24) & 0xffU);
    bytes[1] = static_cast<std::uint8_t>((value >> 16) & 0xffU);
    bytes[2] = static_cast<std::uint8_t>((value >> 8) & 0xffU);
    bytes[3] = static_cast<std::uint8_t>(value & 0xffU);
}

void writeBigEndian64(std::uint64_t value, std::uint8_t* bytes) {
    for (int index = 7; index >= 0; --index) {
        bytes[7 - index] = static_cast<std::uint8_t>((value >> (index * 8)) & 0xffU);
    }
}

}  // namespace

void Sha256::update(const void* data, std::size_t length) {
    const auto* bytes = static_cast<const std::uint8_t*>(data);
    totalBytes_ += length;

    if (bufferSize_ > 0) {
        const auto bytesToCopy = std::min(length, buffer_.size() - bufferSize_);
        std::memcpy(buffer_.data() + bufferSize_, bytes, bytesToCopy);
        bufferSize_ += bytesToCopy;
        bytes += bytesToCopy;
        length -= bytesToCopy;

        if (bufferSize_ == buffer_.size()) {
            processBlock(buffer_.data());
            bufferSize_ = 0;
        }
    }

    while (length >= buffer_.size()) {
        processBlock(bytes);
        bytes += buffer_.size();
        length -= buffer_.size();
    }

    if (length > 0) {
        std::memcpy(buffer_.data(), bytes, length);
        bufferSize_ = length;
    }
}

void Sha256::update(std::string_view data) {
    update(data.data(), data.size());
}

std::array<std::uint8_t, 32> Sha256::finalize() {
    const auto totalBits = totalBytes_ * 8;

    buffer_[bufferSize_++] = 0x80U;
    if (bufferSize_ > 56) {
        std::fill(buffer_.begin() + static_cast<std::ptrdiff_t>(bufferSize_), buffer_.end(), 0);
        processBlock(buffer_.data());
        bufferSize_ = 0;
    }

    std::fill(buffer_.begin() + static_cast<std::ptrdiff_t>(bufferSize_), buffer_.begin() + 56, 0);
    writeBigEndian64(totalBits, buffer_.data() + 56);
    processBlock(buffer_.data());

    std::array<std::uint8_t, 32> digest{};
    for (std::size_t index = 0; index < state_.size(); ++index) {
        writeBigEndian32(state_[index], digest.data() + (index * 4));
    }
    return digest;
}

void Sha256::processBlock(const std::uint8_t* block) {
    std::array<std::uint32_t, 64> words{};
    for (std::size_t index = 0; index < 16; ++index) {
        words[index] = readBigEndian32(block + (index * 4));
    }

    for (std::size_t index = 16; index < words.size(); ++index) {
        const auto s0 = rotateRight(words[index - 15], 7) ^ rotateRight(words[index - 15], 18) ^ (words[index - 15] >> 3);
        const auto s1 = rotateRight(words[index - 2], 17) ^ rotateRight(words[index - 2], 19) ^ (words[index - 2] >> 10);
        words[index] = words[index - 16] + s0 + words[index - 7] + s1;
    }

    auto a = state_[0];
    auto b = state_[1];
    auto c = state_[2];
    auto d = state_[3];
    auto e = state_[4];
    auto f = state_[5];
    auto g = state_[6];
    auto h = state_[7];

    for (std::size_t index = 0; index < words.size(); ++index) {
        const auto sum1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
        const auto choose = (e & f) ^ ((~e) & g);
        const auto temp1 = h + sum1 + choose + kRoundConstants[index] + words[index];
        const auto sum0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
        const auto majority = (a & b) ^ (a & c) ^ (b & c);
        const auto temp2 = sum0 + majority;

        h = g;
        g = f;
        f = e;
        e = d + temp1;
        d = c;
        c = b;
        b = a;
        a = temp1 + temp2;
    }

    state_[0] += a;
    state_[1] += b;
    state_[2] += c;
    state_[3] += d;
    state_[4] += e;
    state_[5] += f;
    state_[6] += g;
    state_[7] += h;
}

std::string sha256Hex(std::string_view data) {
    Sha256 hasher;
    hasher.update(data);
    return hexEncoded(hasher.finalize());
}

std::string hexEncoded(const std::array<std::uint8_t, 32>& digest) {
    std::ostringstream stream;
    stream << std::hex << std::setfill('0');
    for (const auto byte : digest) {
        stream << std::setw(2) << static_cast<int>(byte);
    }
    return stream.str();
}

}  // namespace autodj::repository::detail
