(defun c:ExportTagData ( / outputDir fileLarge fileAll dict groupName groupData subEnt entData handle layer pt content item pair res xStr yStr memberCount groupList membersList gItem )
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
                       (setq content (cdr (assoc 1 entData)))
                       
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
