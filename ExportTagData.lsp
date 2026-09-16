(defun c:ExportTagData ( / outputDir fileAll fileLarge dict groupName pair res groupData membersList sub entData memberCount subEnt handle layer pt content entType xStr yStr gItem aEnt aData aTag bname blk blkSub blkSubData blkTxt )
  ;; Open both files simultaneously
  ;; The frontend supplies its selected workspace; direct AutoCAD runs fall back
  ;; to the active drawing directory.
  (setq outputDir (getenv "TAGOPS_WORKSPACE"))
  (if (not outputDir) (setq outputDir (getvar "DWGPREFIX")))
  (if (/= (substr outputDir (strlen outputDir) 1) "\\")
    (setq outputDir (strcat outputDir "\\"))
  )
  (setq fileAll (open (strcat outputDir "autocad_groups.csv") "w"))
  (setq fileLarge (open (strcat outputDir "large_groups.csv") "w"))
  
  ;; Write headers to both CSV files
  (write-line "GroupName,Handle,Layer,TextContent,X,Y" fileAll)
  (write-line "GroupName,Handle,Layer,TextContent,X,Y" fileLarge)
  
  (setq dict (dictsearch (namedobjdict) "ACAD_GROUP"))
  (setq groupName "Unnamed")
  
  (if dict
    (foreach pair dict
      (if (= (type pair) 'LIST)
        (progn
          (setq res (car pair))
          (cond
            ;; Capture group name (Group 3)
            ((= res 3)
             (if (= (type (cdr pair)) 'STR)
               (setq groupName (cdr pair))
               (setq groupName "Unnamed")
             )
            )
            ;; Capture group dictionary entry (Group 350)
            ((= res 350)
             (setq groupData (entget (cdr pair)))
             (if groupData
               (progn
                 ;; First pass: collect all valid entity handles/pointers (Group 340) and count members
                 (setq membersList nil)
                 (foreach sub groupData
                   (if (and sub (= (type sub) 'LIST))
                     (if (= (car sub) 340)
                       (progn
                         (setq subEnt (cdr sub))
                         (if (and subEnt (= (type subEnt) 'ENAME))
                           (setq membersList (cons subEnt membersList))
                         )
                       )
                     )
                   )
                 )
                 
                 (setq memberCount (length membersList))
                 
                 ;; Second pass: process and export each member entity found in the group
                 (foreach subEnt membersList
                   (setq entData (entget subEnt))
                   (if entData
                     (progn
                       (setq handle (cdr (assoc 5 entData)))
                       (setq layer (cdr (assoc 8 entData)))
                       (setq pt (cdr (assoc 10 entData)))
                       (setq entType (cdr (assoc 0 entData)))
                       (setq content nil)
                       
                       (cond
                         ((= entType "MULTILEADER")
                          (setq content (cdr (assoc 304 entData)))
                         )
                         ((= entType "INSERT")
                          ;; First check if the block definition contains embedded TEXT (e.g. line tag like 219-PG-C1C5-X050)
                          (setq bname (cdr (assoc 2 entData)))
                          (if bname
                            (progn
                              (setq blk (tblobjname "BLOCK" bname))
                              (if blk
                                (progn
                                  (setq blkSub blk)
                                  (while (setq blkSub (entnext blkSub))
                                    (setq blkSubData (entget blkSub))
                                    (if (or (= (cdr (assoc 0 blkSubData)) "TEXT") (= (cdr (assoc 0 blkSubData)) "MTEXT"))
                                      (progn
                                        (setq blkTxt (cdr (assoc 1 blkSubData)))
                                        (if (and blkTxt (/= blkTxt "") (not (wcmatch (strcase blkTxt) "*EL.*,*N.*,*E.*,*W.*")))
                                          (setq content blkTxt)
                                        )
                                      )
                                    )
                                  )
                                )
                              )
                            )
                          )
                          ;; If no in-block text was found, fall back to checking attributes
                          (if (or (not content) (= content ""))
                            (if (= (cdr (assoc 66 entData)) 1)
                              (progn
                                (setq aEnt (entnext subEnt))
                                (while (and aEnt (/= (cdr (assoc 0 (entget aEnt))) "SEQEND"))
                                  (setq aData (entget aEnt))
                                  (setq aTag (vl-string-trim " " (strcase (cdr (assoc 2 aData)))))
                                  (if (or (= aTag "VLV_TAG") (= aTag "VLV_NUM") (= aTag "TAG") (= aTag "PIPE REF") (= aTag "PIPE_REF") (= aTag "PIPEREF")
                                          (and (wcmatch (strcase bname) "*CABLE*") (= aTag "TAG1"))
                                      )
                                    (setq content (cdr (assoc 1 aData)))
                                  )
                                  (setq aEnt (entnext aEnt))
                                )
                              )
                            )
                          )
                         )
                         (t
                          (setq content (cdr (assoc 1 entData)))
                         )
                       )
                       
                       (if (not content) (setq content ""))
                       (if (not handle) (setq handle ""))
                       (if (not layer) (setq layer ""))
                       
                       (if (and pt (listp pt) (numberp (car pt)))
                         (setq xStr (rtos (car pt) 2 3))
                         (setq xStr "0")
                       )
                       
                       (if (and pt (listp pt) (numberp (cadr pt)))
                         (setq yStr (rtos (cadr pt) 2 3))
                         (setq yStr "0")
                       )
                       
                       ;; Format the CSV row string
                       (setq gItem (strcat "\"" groupName "\",\"" handle "\",\"" layer "\",\"" content "\"," xStr "," yStr))
                       
                       ;; Always write to the all-groups file
                       (write-line gItem fileAll)
                       
                       ;; Conditionally write to large_groups.csv if group has strictly more than 2 members
                       (if (> memberCount 2)
                         (write-line gItem fileLarge)
                       )
                     )
                   )
                 )
               )
             )
            )
          )
        )
      )
    )
  )
  
  ;; Close both file streams
  (close fileAll)
  (close fileLarge)
  
  (princ "\nTag export complete! Both CSV files saved successfully.")
  (princ)
)
