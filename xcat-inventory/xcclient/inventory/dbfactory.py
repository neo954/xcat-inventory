#!/usr/bin/python
from __future__ import print_function
import sys
from sqlalchemy import or_
from sqlalchemy.orm.attributes import InstrumentedAttribute as Col_type

try:
    from . import dbobject
    from .dbobject import *
except Exception:
    print("Failed to connected with database...")

from .exceptions import *
from . import utils

def create_or_update(session,tabcls,key,newdict,ismatrixtable=True):
    tabkeys=tabcls.primkeys()
    #for matrix table, remove the record if all the non-key values are None or blank 
    delrow=1 
    #for flat table, keep the record untouch if the non-key values are None
    skiprow=1
    
    objkeys=tabcls.getobjkey()
  
    if type(key) not in (list,tuple):
        key=[key] 
    keyvals=zip(objkeys,key)
    for (keyname,keyval)  in keyvals:
        newdict[keyname]=keyval

    tabcols=tabcls.getcolumns()
    for item in newdict.keys():
        if item not in tabcols:
            if newdict[item] is None:
                del newdict[item] 
                continue
            else:
                raise BadSchemaException("Error: no column '"+item+"' in table "+tabcls.__tablename__+", might caused by mismatch between schema version and xCAT version!")
            
        if item not in objkeys and newdict[item]:
            skiprow=0        
            delrow=0

        if  item not in objkeys and newdict[item] is None:
            newdict[item]=''
        
        #delete table rows when (1)the object keys are None or blank (2)the key is not specified in newdict and all non-key values are blank 
        if item not in objkeys and newdict[item]!='': 
            delrow=0

        if item == 'disable' and newdict[item]=='':
            newdict[item]=None
   
    if not ismatrixtable:
        if skiprow:
            return
        #do not remove for flat table
        delrow=0

    #if tabcls.__tablename__=='switch':
    #    import pdb
    #    pdb.set_trace()
    try:
        query=session.query(tabcls)
        for tabkey in tabkeys:
            query=query.filter(getattr(tabcls,tabkey) == newdict[tabkey])
        record=query.all()
    except Exception as e:
        raise DBException("Error: query xCAT table "+tabcls.__tablename__+" failed: "+str(e))
    if record:
        if delrow:
            try:
                for item in record:
                    session.delete(item)
            except Exception as e:
                raise DBException("Error: delete "+key+" is failed: "+str(e))
            #else:
            #    print("delete row in xCAT table "+tabcls.__tablename__+".")
        else:
           try:
               #query=session.query(tabcls)
               #for tabkey in tabkeys:
               #    query=query.filter(getattr(tabcls,tabkey) == newdict[tabkey])
               query.update(newdict)
           except Exception as e:
               raise DBException("Error: import object "+key+" is failed: "+str(e))
    elif delrow == 0:
        try:
            session.execute(tabcls.__table__.insert(), newdict)
        except Exception as e:
            raise DBException("Error: import object "+key+" is failed: "+str(e)) 

class matrixdbfactory():
    def __init__(self,dbsession):
        self._dbsession=dbsession

    def gettab(self,tabs,keys=[]):    
        ret={}
        for tabname in tabs:
           dbsession=self._dbsession.loadSession(tabname); 
           if hasattr(dbobject,tabname):
               tab=getattr(dbobject,tabname)
           else:
               continue
           tabobjs=[]
           tabkeys=tab.primkeys()
           if not keys or len(keys)==0:
               tabobjs=dbsession.query(tab).filter(or_(tab.disable == None, tab.disable.notin_(['1','yes']))).all()
           elif len(tabkeys)==1:
               tabobjs = dbsession.query(tab).filter(getattr(tab, tabkeys[0]).in_(keys),
                                                     or_(tab.disable == None, tab.disable.notin_(['1', 'yes']))).all()
           elif len(tabkeys)>1:
               for key in keys:
                   if type(key)!=tuple:
                       key=[key]
                   kvdict=dict(zip(tabkeys,key))
                   query=dbsession.query(tab)
                   for key,value in kvdict.items():
                       query=query.filter(getattr(tab,key).in_([value]))
                   query=query.filter(or_(tab.disable == None, tab.disable.notin_(['1','yes'])))  
                   tabobj=query.all()
                   tabobjs.extend(tabobj)
           if not tabobjs:
               continue

           objkeyname=tab.getobjkey()
           dictoftab={}
           for myobj in tabobjs:
               mydict=myobj.getdict()

               if len(objkeyname)==1:
                   mykey=mydict[tab.__tablename__+'.'+objkeyname[0]]
               elif len(objkeyname)>1:
                   mykeylist=[]
                   for key in objkeyname:
                       mykeylist.append(mydict[tab.__tablename__+'.'+key])  
                   mykey=tuple(mykeylist)

               if mykey not in dictoftab.keys():
                   dictoftab[mykey]=mydict
               else:
                   if type(dictoftab[mykey])!=list:
                       dictoftab[mykey]=[dictoftab[mykey]]
                   dictoftab[mykey].append(mydict)


           for mykey in dictoftab.keys():
               if mykey not in ret.keys():
                   ret[mykey]={}
               if type(dictoftab[mykey])==list:
                   if tabname not in ret[mykey].keys():
                       ret[mykey][tabname]=[]
                   ret[mykey][tabname].extend(dictoftab[mykey])
               else:
                   ret[mykey].update(dictoftab[mykey])

        for mykey in ret.keys():
            if len(ret[mykey].keys())==1 and list(ret[mykey].keys())[0] in tabs :
                ret[mykey]=ret[mykey][list(ret[mykey].keys())[0]]

        return ret 

    def settab(self,tabdict=None):
        #print("=========matrixdbfactory:settab========")
        #print(tabdict)
        #print("\n")
        if tabdict is None:
            return None
        for key in tabdict.keys():
            utils.verbose("  writting object: "+str(key),file=sys.stdout)
            #clear any existing table entries before adding new entries
            df=dbfactory(self._dbsession) 
            df.cleartab(tabdict[key].keys(),[key])
            for tab in tabdict[key].keys():
                dbsession=self._dbsession.loadSession(tab);
                if hasattr(dbobject,tab):
                    tabcls=getattr(dbobject,tab)
                else:
                    continue

                for record in tabdict[key][tab]:
                    if tabcls.isValid(key,record):
                        create_or_update(dbsession,tabcls,key,record)


class flatdbfactory() :
    def __init__(self,dbsession):
        self._dbsession=dbsession

    def gettab(self, tabs, keys=None):
        ret={}
        if keys:
            rootkey=keys[0]
        else:
            rootkey='clustersite'
        ret[rootkey]={}
        for tabname in tabs:
            dbsession=self._dbsession.loadSession(tabname)
            if hasattr(dbobject,tabname):
                tab=getattr(dbobject,tabname)
            else:
                continue
            tabobj=dbsession.query(tab).filter(or_(tab.disable == None,tab.disable.notin_(['1','yes']))).all()
            if not tabobj:
                continue
            for myobj in tabobj:
                mydict=myobj.getdict()
                ret[rootkey].update(mydict)
        return ret
   
    def settab(self, tabdict=None):
        #print("======flatdbfactory:settab======")
        #print(tabdict)
        if tabdict is None:
            return None
        for key in tabdict.keys():
            for tab in tabdict[key].keys():
                if hasattr(dbobject,tab):
                    tabcls=getattr(dbobject,tab)
                else:
                    continue
                tabkey=tabcls.getobjkey()[0]
                rowentlist=tabcls.dict2tabentry(tabdict[key][tab][0])
                dbsession=self._dbsession.loadSession(tab)
                for rowent in rowentlist:
                    if tabcls.isValid(key, rowent):
                        create_or_update(dbsession,tabcls,rowent[tabkey],rowent,False)


class dbfactory():
    
    def __init__(self,dbsession):
        self._dbsession=dbsession

    def gettab(self,tabs,keys=None):
        flattabs=[]
        matrixtabs=[]
        mydict={}

        for tab in tabs:
            if hasattr(dbobject,tab):
                tabcls=getattr(dbobject,tab)
            else:
                continue       
            if tabcls.getTabtype() == 'flat':
                flattabs.append(tab)
            else:
                matrixtabs.append(tab)
        if flattabs:
            df_flat=flatdbfactory(self._dbsession)
            mydict.update(df_flat.gettab(flattabs,keys))
        if matrixtabs:
            df_matrix=matrixdbfactory(self._dbsession)
            mydict.update(df_matrix.gettab(matrixtabs,keys))
        return mydict
    
    #convert db dict from format {key:{tab.col=value}} to {key:{tab:{col}}}
    def __tabtransform(self,dbdict):
        #print("__tabtransform")
        #print(dbdict)
        flattabdict={}
        matrixtabdict={}

        #try:
        for key in dbdict.keys():
            dbentlist=[]
            rawdbents=dbdict[key]
            if type(rawdbents)==dict:
                dbentlist.append(rawdbents)
            else:
                dbentlist.extend(rawdbents)  
   

            for dbent in dbentlist:
                #print("@@@@@@@@@@@@")
                #print(dbent)
                #print("@@@@@@@@@@@@")
                rowdict={}
                for tabcol in dbent.keys():
                    (tab,col)=tabcol.split('.')

                    if tab not in rowdict.keys():
                        rowdict[tab]={}
                    if col not in rowdict[tab].keys():
                        rowdict[tab][col]={}
                    rowdict[tab][col]=dbent[tabcol] 


                for tab in rowdict.keys():
                    if hasattr(dbobject,tab):
                        tabcls=getattr(dbobject,tab)
                    else:
                        continue       
                    if tabcls.getTabtype() == 'flat':
                        if key not in flattabdict.keys():
                            flattabdict[key]={}
                        if tab not in flattabdict[key].keys():
                            flattabdict[key][tab]=[]
                        flattabdict[key][tab].append(rowdict[tab])
                    else:
                        if key not in matrixtabdict.keys():
                            matrixtabdict[key]={}
                        if tab not in matrixtabdict[key].keys():
                            matrixtabdict[key][tab]=[]
                        matrixtabdict[key][tab].append(rowdict[tab])
        return(matrixtabdict,flattabdict)
     
                
    def settab(self,dbdict=None):                 
        if dbdict is None:
            return None
        (matrixtabdict,flattabdict)=self.__tabtransform(dbdict)
        if flattabdict:
            df_flat=flatdbfactory(self._dbsession)
            mydict=df_flat.settab(flattabdict)
        if matrixtabdict: 
            df_matrix=matrixdbfactory(self._dbsession)
            mydict=df_matrix.settab(matrixtabdict)  
        #except Exception as e:
        #  raise ("Error: import object failed.")
        #else:
        #    print("import object successfully.")          

    def cleartab(self,tabs,objkey=[]):
        for tab in tabs:
            if hasattr(dbobject,tab):
                tabcls=getattr(dbobject,tab)
            else:
                continue
            tabkey=tabcls.getobjkey()[0]
            ReservedKeys=tabcls.getReservedKeys()
            dbsession=self._dbsession.loadSession(tab)
            try:
                query=dbsession.query(tabcls)
                query=query.filter(or_(tabcls.disable == None, tabcls.disable.notin_(['1','yes'])))
                if ReservedKeys:
                    query=query.filter(getattr(tabcls,tabkey).notin_(ReservedKeys))        
                    
                if objkey:
                    query=query.filter(getattr(tabcls,tabkey).in_(objkey)) 
                query.delete(synchronize_session='fetch')
            except Exception as e:
                raise DBException("Error: failed to clear table "+str(tab)+": "+str(e))
        #else:
        #    print("table "+tab+ "cleared!")

    def addtabentries(self,tab,objdict):
        if hasattr(dbobject,tab):
            tabcls=getattr(dbobject,tab)
        else:
            raise DBException("Error: cannot find table '%s'" % tab)
        tabkeys=tabcls.primkeys()
        try:
            dbsession=self._dbsession.loadSession(tab)
            query=dbsession.query(tabcls)
            for tabkey in tabkeys:
                query=query.filter(getattr(tabcls,tabkey) == objdict[tabkey])
            record=query.all()
            if record:
                raise DBException("this user exist")
            else:
                dbsession.execute(tabcls.__table__.insert(), objdict)
        except Exception as e:
            raise DBException("Error: "+str(tab)+": "+str(e))

    def updatetabentries(self,tab,objdict):
        if hasattr(dbobject,tab):
            tabcls=getattr(dbobject,tab)
        else:
            raise DBException("Error: cannot find table '%s'" % tab)
        tabkeys=tabcls.primkeys()
        try:
            dbsession=self._dbsession.loadSession(tab)
            query=dbsession.query(tabcls)
            wherecl=''
            for tabkey in tabkeys:
                query=query.filter(getattr(tabcls,tabkey) == objdict[tabkey])
                del objdict[tabkey]
            query.update(objdict)
        except Exception as e:
            raise DBException("Error: "+str(tab)+": "+str(e))

    def deltabentries(self,tab,objdict):
        if hasattr(dbobject,tab):
            tabcls=getattr(dbobject,tab)
        else:
            raise DBException("Error: cannot find table '%s'" % tab)
        tabkeys=tabcls.primkeys()
        try:
            dbsession=self._dbsession.loadSession(tab)
            query=dbsession.query(tabcls)
            for tabkey in tabkeys:
                query=query.filter(getattr(tabcls,tabkey) == objdict[tabkey])
            query.delete(synchronize_session='fetch')
            
        except Exception as e:
            raise DBException("Error:"+str(tab)+": "+str(e))

    def getcolumns(self, tab, cols, keys=None):
        """Fetches columns from table with specified keys.

        Retrieves columns pertaining to the given keys from the Tables.

        Args:
            tab: table name.
            cols: A list of columns.
            keys: A sequence of strings representing the key of each table row
                to fetch.

        Returns:
            A dict mapping keys to the corresponding table row data
            fetched. Each row is represented as a tuple of strings. For
            example:

                {
                 'node1':{'groups':'all,my_group'},
                 'node2':{'groups':'all,my_group'}
                }

            If a key from the keys argument is missing from the dictionary,
            then that row was not found in the table.

        Raises:
            DBException: An error occurred accessing the database.
        """
        if hasattr(dbobject, tab):
            tabcls=getattr(dbobject, tab)
        else:
            raise DBException("Error: cannot find table '%s'" % tab)

        # TODO, only support table with one primary key now
        tabkeys = tabcls.primkeys()
        if len(tabkeys) != 1:
            raise DBException("Error: 'getcolumns' only support table with one primary key, while table %s has %d." % (tab, len(tabkeys)))

        # adjust the primary key column into cols
        obj_key = tabcls.getobjkey()
        adjusted_cols = list(obj_key)
        adjusted_cols.extend([c for c in cols if c != obj_key])

        mydict=dict()
        try:
            # Create a query object for the table
            dbsession = self._dbsession.loadSession(tab)
            q = dbsession.query()

            # Add the specified columns to query
            for c in adjusted_cols:
                try:
                    col = getattr(nodelist, c)
                    if type(col) is not Col_type:
                        raise AttributeError

                    q = q.add_column(col)
                except AttributeError:
                    raise DBException("Not found column '%s'" % c)

            # Add the filter to query (1, exclude disable; 2, using primary key to limit the scope)
            # and do the query, the result will be a tuple: [(u'node1', u'all,my_group'), (u'node2', u'all,my_group')]
            if not keys:
                result = q.filter(or_(tabcls.disable == None, tabcls.disable.notin_(['1','yes']))).all()
            else:
                result = q.filter(getattr(tabcls, tabkeys[0]).in_(keys),
                                  or_(tabcls.disable == None, tabcls.disable.notin_(['1', 'yes']))).all()

            # Convert the tuple format result to dict
            if not result:
                return mydict

            for row in result:
                row_d = dict()
                for i, val in enumerate(adjusted_cols):
                    # ignore the primary key column
                    if not i:
                        continue
                    row_d[val] = row[i]
                mydict[row[0]] = row_d

            return mydict

        except Exception as e:
            raise DBException("Error: %s: %s" % (tabcls, e))

