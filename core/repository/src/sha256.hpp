#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>

namespace autodj::repository::detail {

class Sha256 final {
public:
    void update(const void* data, std::size_t length);
    void update(std::string_view data);

    [[nodiscard]] std::array<std::uint8_t, 32> finalize();

private:
    void processBlock(const std::uint8_t* block);

    std::array<std::uint32_t, 8> state_{
        0x6a09e667U,
        0xbb67ae85U,
        0x3c6ef372U,
        0xa54ff53aU,
        0x510e527fU,
        0x9b05688cU,
        0x1f83d9abU,
        0x5be0cd19U,
    };
    std::array<std::uint8_t, 64> buffer_{};
    std::uint64_t totalBytes_ = 0;
    std::size_t bufferSize_ = 0;
};

[[nodiscard]] std::string sha256Hex(std::string_view data);
[[nodiscard]] std::string hexEncoded(const std::array<std::uint8_t, 32>& digest);

}  // namespace autodj::repository::detail
