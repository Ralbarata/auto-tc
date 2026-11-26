;; Survei baca-saja: layer marka + daftar hatch di model space
(vl-load-com)
(defun c3dt-survey ( / f l ss i e d r a b p q s2)
  (setq f (open "C:/Users/USER/AUTO TC by rangga/C3DTools/_survey.txt" "w"))
  (setq l (tblnext "LAYER" T))
  (while l
    (if (wcmatch (strcase (cdr (assoc 2 l))) "*MARK*,*STRIP*,*ZEBRA*,*CHEVRON*")
      (write-line (strcat "LAYER;" (cdr (assoc 2 l))) f))
    (setq l (tblnext "LAYER")))
  (setq ss (ssget "X" '((0 . "HATCH") (410 . "Model"))) i 0)
  (if ss
    (repeat (sslength ss)
      (setq e (ssname ss i) d (entget e)
            r (vl-catch-all-apply 'vla-getboundingbox (list (vlax-ename->vla-object e) 'a 'b)))
      (if (vl-catch-all-error-p r)
        (write-line (strcat "H;" (cdr (assoc 8 d)) ";" (cdr (assoc 2 d)) ";ERR") f)
        (progn
          (setq p (vlax-safearray->list a) q (vlax-safearray->list b))
          (write-line (strcat "H;" (cdr (assoc 8 d)) ";" (cdr (assoc 2 d)) ";"
                              (rtos (car p) 2 2) ";" (rtos (cadr p) 2 2) ";"
                              (rtos (car q) 2 2) ";" (rtos (cadr q) 2 2) ";"
                              (cdr (assoc 5 d)) ";" (itoa (if (assoc 62 d) (cdr (assoc 62 d)) 256))) f)))
      (setq i (1+ i))))
  (setq s2 (ssget "X" '((8 . "MARKA*"))))
  (write-line (strcat "MARKA-OBJ;" (itoa (if s2 (sslength s2) 0))) f)
  (write-line "END" f)
  (close f)
  (princ "\nSURVEY-DONE")
  (princ))
(c3dt-survey)
