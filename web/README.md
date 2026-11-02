Install: `../setup.sh bootstrap`
Dev: `"$(command -v mise || printf ../.tools/bin/mise)" exec -- npm run dev`
Build: `make -C .. web-build`
Regenerate registry: `make -C .. references`
