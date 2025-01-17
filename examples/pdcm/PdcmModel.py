from netpyne import specs, sim
from neuron import h
from netpyneunit.models import NetpyneModel
from netpyneunit.models.backends import NetpyneBackend
import numpy as np
from capabilities import ProducesMeanFiringRate
from sciunit.models.backends import register_backends
register_backends({"Netpyne": NetpyneBackend})

class PdcmModel(NetpyneModel, ProducesMeanFiringRate):

  def __init__(self, name, scale, ext_input, duration=60*1e3):
    super().__init__(name=name, backend=("Netpyne", { "use_memory_cache": True, "use_disk_cache": False }))
    self.scale     = scale
    self.ext_input = ext_input
    self.duration  = duration

  def initSim(self):
    cfg = self.getSimConfig()
    netParams = self.getNetParams(cfg)
    sim.initialize(simConfig=cfg, netParams=netParams)

    sim.net.createPops()
    sim.net.createCells()

    # randomize m parameter of cells
    rand = h.Random()
    for c in sim.net.cells:
      if c.tags['cellModel'] == 'IntFire_PD':
        rand.Random123(c.gid, sim.cfg.seeds['m'])
        c.hPointp.m = rand.normal(-58,10)

  def getSimConfig(self):
    cfg = specs.SimConfig()

    cfg.seeds['stim'] = 0
    cfg.duration = self.duration
    cfg.dt = 0.025
    cfg.seeds['m'] = 0
    cfg.printPopAvgRates = False # Still prints?
    cfg.printRunTime = 1

    ### Options to save memory in large-scale ismulations
    cfg.gatherOnlySimData = False
    cfg.saveCellSecs      = False
    cfg.saveCellConns     = False
    cfg.createPyStruct    = False

    # DC=True ; TH=False; Balanced=True  => Reproduce Figure 7 A1 and A2
    # DC=False; TH=False; Balanced=False => Reproduce Figure 7 B1 and B2
    # DC=False; TH=False; Balanced=True  => Reproduce Figure 8 A, B, C and D
    # DC=False; TH=False; Balanced=True and run to 60 s => Table 6 
    # DC=False; TH=True;  Balanced=True  => Figure 10A. But I want a partial reproduce so I guess Figure 10C is not necessary

    cfg.ScaleFactor = self.scale

    if (self.ext_input == 'balanced_poisson'):
      cfg.DC = False
      cfg.Balanced = True
    elif (self.ext_input == 'balanced_dc'):
      cfg.DC = True
      cfg.Balanced = True
    elif (self.ext_input == 'unbalanced_poisson'):
      cfg.DC = False
      cfg.Balanced = False
    else:
      raise ValueError(f'ext_input should be not be "{self.ext_input}".')

    # Thalamic input in 4th and 6th layer on or off
    cfg.TH = False #True = on // False = off

    cfg.simLabel = 'pd_scale-%s_DC-%d_TH-%d_Balanced-%d_dur-%d_Seed-%d'%(str(cfg.ScaleFactor), int(cfg.DC), int(cfg.TH), int(cfg.Balanced), int(cfg.duration/1e3), int(cfg.seeds['stim']))

    ###########################################################
    # Recording and plotting options
    ###########################################################

    cfg.recordStep = 0.1 # Step size in ms to save data (e.g. V traces, LFP, etc)
    cfg.saveFolder = 'data/'
    cfg.savePickle = True
    cfg.saveJson = False
    cfg.recordStim = False
    cfg.printSynsAfterRule = False
    cfg.recordCellsSpikes = ['L2e', 'L2i', 'L4e', 'L4i', 'L5e', 'L5i','L6e', 'L6i'] # record only spikes of cells (not ext stims)

    # raster plot (include update in netParams.py)
    # cfg.analysis['plotRaster'] = {
    #   # cfg.duration used to be simply '600' in a copypasted comment
    #   'include': [], 'timeRange': [100, cfg.duration], 'popRates' : False, 'figSize': (6,7),
    #   'labels':'overlay', 'orderInverse': True, 'fontSize':16, 'showFig':False, 'saveFig': True, 'saveData':True
    # }

    # statistics plot (include update in netParams.py)
    cfg.analysis['plotSpikeStats'] = {
      'include': cfg.recordCellsSpikes, 'stats': ['rate','isicv'], 'legendLabels': cfg.recordCellsSpikes,
      'timeRange': [100,cfg.duration], 'fontSize': 16, 'figSize': (6,9),'showFig': False, 'saveFig': True, 'saveData': True
    }

    # plot traces
    # cfg.recordTraces = {'m': {'var': 'm', 'conds':{'pop': ['L2e', 'L2i']}}}
    # cfg.analysis['plotTraces'] = {'include':[('L2e', [0, 1, 2, 3]),('L2i', [0, 1])], 'timeRange': [0,100],'overlay': True,'oneFigPer': 'trace', 'showFig':False, 'saveFig': 'traceEscala3'+str(cfg.ScaleFactor)+'.png'}
    return cfg

  def getNetParams(self, cfg):
    print("Initializing netParams")

    # Reescaling function (move to separate module?)
    def Reescale(ScaleFactor, C, N_Full, w_p, f_ext, tau_syn, Inp, InpDC):
      if ScaleFactor<1.0 : 
        # 1
        F_out=np.array([0.860, 2.600, 4.306, 5.396, 8.142, 8.188, 0.941, 7.3]) #Good approximation
        #F_out=array([0.971, 2.868, 4.746, 5.396, 8.142, 9.078, 0.991, 7.523])
        
        #Para a nao balanceada o F_out deve ser outro. O nao balanceado. Apos corrigir conexoes testar para caso so de aleracao no InpPoiss
        Ncon=np.vstack(np.column_stack(0 for i in range(0,8)) for i in range(0,8))
        for r in range(0,8): 
          for c in range(0,8): 
            Ncon[r][c]=(np.log(1.-C[r][c])/np.log(1. -1./(N_Full[r]*N_Full[c])) ) /N_Full[r]

        w=w_p*np.column_stack(np.vstack( [1.0, -4.0] for i in range(0,8)) for i in range(0,4))
        w[0][2]=2.0*w[0][2]

        x1_all = w * Ncon * F_out
        x1_sum = np.sum(x1_all, axis=1)
        x1_ext = w_p * Inp * f_ext
        I_ext=np.column_stack(0 for i in range(0,8))
        I_ext = 0.001 * tau_syn * (
                (1. - np.sqrt(ScaleFactor)) * x1_sum + 
                (1. - np.sqrt(ScaleFactor)) * x1_ext)
        #if ScaleFactor<0.09:  #Aqui adaptado
        # I_ext=1.2*I_ext #1.05 da ativo 1.4
                    
        #Inp=ScaleFactor*Inp*w_p*f_ext*tau_syn*0.001
        InpDC=np.sqrt(ScaleFactor)*InpDC*w_p*f_ext*tau_syn*0.001 #pA
        w_p=w_p/np.sqrt(ScaleFactor) #pA
        InpDC=InpDC+I_ext
        N_=[int(ScaleFactor*N) for N in N_Full]
      else:
        InpDC=InpDC*w_p*f_ext*tau_syn*0.001
        N_=N_Full 
      
      return InpDC, N_, w_p


    ###########################################################
    #  Network Constants
    ###########################################################

    # Frequency of external input
    f_ext=8.0 # (Hz)
    # Postsynaptic current time constant
    tau_syn=0.5 # (ms)
    # Membrane time constant
    tau_m=10 # (ms)
    # Other constants defined inside .mod
    '''
    #Absolute refractory period
    tauref =2 (ms) 
    #Reset potential
    Vreset = -65 (mV) : -49 (mV) :
    #Fixed firing threshold
    Vteta  = -50 (mV)'''
    # Membrane capacity
    C_m=250 #pF
    # Mean amplitude of the postsynaptic potential (in mV).
    w_v=0.15
    # Mean amplitude of the postsynaptic potential (in pA).
    w_p= (((C_m) ** (-1) * tau_m * tau_syn / (
            tau_syn - tau_m) * ((tau_m / tau_syn) ** (
                - tau_m / (tau_m - tau_syn)) - (tau_m / tau_syn) ** (
                - tau_syn / (tau_m - tau_syn)))) ** (-1))
    w_p=w_v*w_p #(pA)

    #C probability of connection
    C=np.array([
      [0.1009, 0.1689, 0.0437, 0.0818, 0.0323, 0.,     0.0076, 0.],
      [0.1346, 0.1371, 0.0316, 0.0515, 0.0755, 0.,     0.0042, 0.],
      [0.0077, 0.0059, 0.0497, 0.135,  0.0067, 0.0003, 0.0453, 0.],
      [0.0691, 0.0029, 0.0794, 0.1597, 0.0033, 0.,     0.1057, 0.],
      [0.1004, 0.0622, 0.0505, 0.0057, 0.0831, 0.3726, 0.0204, 0.],
      [0.0548, 0.0269, 0.0257, 0.0022, 0.06,   0.3158, 0.0086, 0.],
      [0.0156, 0.0066, 0.0211, 0.0166, 0.0572, 0.0197, 0.0396, 0.2252],
      [0.0364, 0.001,  0.0034, 0.0005, 0.0277, 0.008,  0.0658, 0.1443]
    ]) 

    #Population size N
    L=['L2e', 'L2i', 'L4e', 'L4i', 'L5e', 'L5i', 'L6e', 'L6i']
    N_Full=np.array([20683, 5834, 21915, 5479, 4850, 1065, 14395, 2948, 902])

    # Number of Input per Layer
    Inp=np.array([1600, 1500, 2100, 1900, 2000, 1900, 2900, 2100])
    if cfg.Balanced == False:
      InpUnb=np.array([2000, 1850, 2000, 1850, 2000, 1850, 2000, 1850])

    ###########################################################
    # Reescaling calculation
    ###########################################################
    if cfg.DC == True:
      InpDC = Inp
      if cfg.Balanced == False:
        InpDC = InpUnb
    else: 
      InpDC = np.zeros(8)
      InpPoiss = Inp * cfg.ScaleFactor
      if cfg.Balanced == False:
        InpPoiss = InpUnb*cfg.ScaleFactor

    InpDC, N_, w_p = Reescale(cfg.ScaleFactor, C, N_Full, w_p, f_ext, tau_syn, Inp, InpDC)


    ############################################################
    # NetPyNE Network Parameters (netParams)
    ############################################################

    netParams = specs.NetParams()  # object of class NetParams to store the network parameters

    netParams.delayMin_e = 1.5
    netParams.ddelay = 0.5
    netParams.delayMin_i = 0.75
    netParams.weightMin = w_p
    netParams.dweight = 0.1

    ############################################################
    # Populations parameters
    ############################################################

    for i in range(0,8):
      netParams.popParams[L[i]] = {'cellType': str(L[i]), 'numCells': int(N_[i]), 'cellModel': 'IntFire_PD', 'm':0, 'Iext':float(InpDC[i])}

    # To atualization of Point Neurons
    netParams.popParams['bkg_IF'] = {'numCells': 1, 'cellModel': 'NetStim','rate': 40000,  'start':0.0, 'noise': 0.0, 'delay':0}

    ############################################################
    # External input parameters
    ############################################################

    if cfg.DC == False: # External Input as Poisson
      for r in range(0,8):
        netParams.popParams['poiss'+str(L[r])] = {
          'numCells': N_[r], 
          'cellModel': 'NetStim',
          'rate': InpPoiss[r]*f_ext,   
          'start': 0.0, 
          'noise': 1.0, 
          'delay': 0
        }

        auxConn=np.array([range(0,N_[r],1),range(0,N_[r],1)])
        netParams.connParams['poiss->'+str(L[r])] = {
          'preConds': {'pop': 'poiss'+str(L[r])},  
          'postConds': {'pop': L[r]},
          'connList': auxConn.T,   
          'weight': 'max(0, weightMin+normal(0,dweight*weightMin))',  
          'delay': 0.5
        } # 1 delay

    # Thalamus Input: increased of 15Hz that lasts 10 ms
    # 0.15 fires in 10 ms each 902 cells -> number of spikes = T*f*N_ = 0.15*902 -> 1 spike each N_*0.15
    if cfg.TH == True:
      fth=15 #Hz
      Tth=10 #ms
      InTH=[0, 0, 93, 84, 0, 0, 47, 34]
      for r in [2,3,6,7]:
        nTH=int(np.sqrt(cfg.ScaleFactor)*InTH[r]*fth*Tth/1000)
        netParams.popParams['bkg_TH'+str(L[r])] = {'numCells': N_[r], 'cellModel': 'NetStim','rate': 2*(1000*nTH)/Tth ,  'start': 200.0, 'noise': 1.0, 'number': nTH, 'delay':0}
        auxConn=np.array([range(0,N_[r],1),range(0,N_[r],1)])
        netParams.connParams['bkg_TH->'+str(L[r])] = {
          'preConds': {'pop': 'bkg_TH'+str(L[r])},  
          'postConds': {'pop': L[r]},
          'connList': auxConn.T,   
          'weight':'max(0, weightMin +normal(0,dweight*weightMin))',  
          'delay': 0.5} # 1 delay


    ############################################################
    # Connectivity parameters
    ############################################################

    for r in range(0,8):
      for c in range(0,8):
        if (c % 2) == 0:
          if c == 2 and r == 0:
            netParams.connParams[str(L[c])+'->'+str(L[r])] = { 
              'preConds': {'pop': L[c]}, # conditions of presyn cells
              'postConds': {'pop': L[r]}, # conditions of postsyn cells
              'divergence': cfg.ScaleFactor*(np.log(1.-C[r][c])/np.log(1. -1./(N_Full[r]*N_Full[c])) ) /N_Full[c],
              'weight':'2*max(0, weightMin +normal(0,dweight*weightMin))', # synaptic weight
              'delay':'max(0.1, delayMin_e +normal(0,ddelay*delayMin_e))',  # transmission delay (ms)
            }
          else:
            netParams.connParams[str(L[c])+'->'+str(L[r])] = { 
              'preConds': {'pop': L[c]}, # conditions of presyn cells
              'postConds': {'pop': L[r]}, # conditions of postsyn cells
              'divergence': cfg.ScaleFactor*(np.log(1.-C[r][c])/np.log(1. -1./(N_Full[r]*N_Full[c])) ) /N_Full[c],
              'weight':'max(0, weightMin +normal(0,dweight*weightMin))', # synaptic weight
              'delay':'max(0.1, delayMin_e +normal(0,ddelay*delayMin_e))', # transmission delay (ms)
            } # synaptic mechanism
        else:
          netParams.connParams[str(L[c])+'->'+str(L[r])] = { 
            'preConds': {'pop': L[c]}, # conditions of presyn cells
            'postConds': {'pop': L[r]}, # conditions of postsyn cells
            'divergence': cfg.ScaleFactor*(np.log(1.-C[r][c])/np.log(1. -1./(N_Full[r]*N_Full[c])) ) /N_Full[c],
            'weight':'-4*max(0, weightMin +normal(0,dweight*weightMin))', # synaptic weight
            'delay':'max(0.1, delayMin_i +normal(0,ddelay*delayMin_i))',  # transmission delay (ms)
          } # synaptic mechanism

    netParams.connParams['S2->M'] = {
      'preConds': {'pop': 'bkg_IF'}, 
      'postConds': {'cellModel': 'IntFire_PD'},
      'probability': 1, 
      'weight':0, 
      'delay': 0.5
    }

    return netParams

  def produce_mean_firing_rate(self):
    return sim.analysis.popAvgRates()
