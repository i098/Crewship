-- Pyrefly is the Python language server; the binary is on PATH (~/.local/bin), not from Mason.
return {
  {
    "neovim/nvim-lspconfig",
    opts = {
      servers = {
        pyrefly = { mason = false },
      },
    },
  },
}
