# 只作参考，不参与Python生产计算。包版本和输入必须显式固定。
args <- commandArgs(trailingOnly=TRUE)
.libPaths(c(args[1], .libPaths()))
stopifnot(as.character(packageVersion("iglu")) == "4.2.2")
data <- read.csv(args[2], stringsAsFactors=FALSE)
data$time <- as.POSIXct(data$time, tz="Asia/Shanghai")
rows <- lapply(unique(data$id), function(id) {
  current <- data[data$id == id & !is.na(data$gl), ]
  value <- iglu::mage(current, version="ma", direction="service",
                     short_ma=5, long_ma=32, inter_gap=45, max_gap=180,
                     tz="Asia/Shanghai")
  data.frame(id=id, reference_mmol_L=as.numeric(value$MAGE[1])/18)
})
write.csv(do.call(rbind, rows), args[3], row.names=FALSE)
capture.output(sessionInfo(), file=args[4])
