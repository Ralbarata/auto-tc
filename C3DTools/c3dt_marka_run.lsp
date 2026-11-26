(load "C:/Users/USER/AUTO TC by rangga/C3DTools/c3dt_marka_lib.lsp")
(c3dt-log "RUN")
(setq c3dt-reg '((1222.3 3199.5) (3900.5 6099.5) (6700.5 10199.5) (11000.5 14999.5) (15600.5 18221.0)))
;; garis pemisah lajur putus-putus
(foreach r c3dt-reg
  (c3dt-mk 4.21 "Putus" (car r) (cadr r))
  (c3dt-mk -4.21 "Putus" (car r) (cadr r)))
;; garis tepi luar utuh
(foreach r c3dt-reg
  (c3dt-solid 7.57 (car r) (cadr r))
  (c3dt-solid -7.57 (car r) (cadr r)))
;; garis tepi dalam utuh di ruas yang masih kosong
(c3dt-solid 0.85 3900.5 6099.5)
(c3dt-solid -0.85 3900.5 6099.5)
(c3dt-log "END")
(princ "\nC3DT-RUN-DONE")
(princ)
