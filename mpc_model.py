import casadi as ca

class Model:
    def __init__(self, t, x, u, z, p, delta, ode = None, alg = None, para = None, opt=None, stage_cost_func = None, terminal_cost_func = None):
        '''
        Model initialization.
        
        Args:
            t: time variable in ca.SX for time variant system (Nt x 1).
            x: state variables in ca.SX (Nx x 1).
            u: control variables in ca.SX (Nu x 1).
            z: algebraic variables in ca.SX (Nz x 1).
            p: parameter variables in ca.SX （Np x 1).
            delta: sampling interval.
            
            ode: ordinary differential equation (a function returns casadi column vector).
            alg: algebraic function (a function returns casadi column vector).
            para: if the option 'para' is fixed, system parameter in this field should be given.
            opt: option (dictionary).
                1. cont_or_dis: 'cont' for time-continuous ode and alg, 'dis' for time-discrete ode and alg.
                2. integrator: 'RK4' for Runge-Kutte 4th order. 'Eular' for explicit Eular.
                3. para: Parameter varibales. 'fixed' for numerical parameters in ode. 'variable' for symbolic numerical parameter in ode.
            stage_cost_func: casadi function input sequence: x, x reference, u, u reference. (Nx x Nx x Nu x Nu -> R)
            terminal_cost_func: casadi function input sequence: x, x reference (Nx x Nx -> R)
        '''
        # TODO: 1. error handler
        
        if opt is None:
            self.opt = {}
            self.opt['cont_or_dis'] = 'cont'
            self.opt['integrator'] = 'RK4'
            self.opt['para'] = 'fixed'
        else:
            self.opt = opt
        
        # Define variables and parameters
        self.t = t
        self.x = x
        self.u = u
        self.z = z
        self.p = p
        self.delta = delta

        # Get the length of state, input, algebraic variables and parameters
        self.Nt = t.shape[0]
        self.Nx = x.shape[0]
        self.Nu = u.shape[0]
        self.Nz = z.shape[0]
        self.Np = p.shape[0]
        
        
        # Reference trajectory
        
        xr = ca.SX.sym('xr',self.Nx)
        ur = ca.SX.sym('ur',self.Nu)
        self.xr = xr
        self.ur = ur
        
        
        # Stage cost and terminal cost
        self.stage_cost_func = stage_cost_func    #  Lagrange term
        self.terminal_cost_func = terminal_cost_func    #  Mayer term
        
        # Set the ode function
        self.ode = ode
        if  self.opt['para'] == 'fixed':
            self.ode_func = ca.Function("ode_func", [t, x, u, p], [ode(t, x, u, para)])
        elif self.opt['para'] == 'variable':
            self.ode_func = ca.Function("ode_func", [t, x, u, p], [ode(t, x, u, p)])
        else:
            print("parameter type error")
        
        # Set the algebraic function and DAE function
        if alg is not None:
            self.alg = alg
            self.alg_func = ca.Function("alg_func", [t, x, u, p, z], [alg(t, x, u, p, z)])    #  Algebraic function
            self.dae_func = ca.Function("dae_func", [t, x, u, p, z], [ca.vertcat(ode(t, x, u, p), alg(t, x, u, p, z))])   #  DAE
            
        # Discretize the ode model
        if self.opt['cont_or_dis'] == 'cont':
            self.ode_cont_model = self.ode_func(t, x, u, p)
            self.ode_cont_func = self.ode_func
            if self.opt['integrator'] == 'Eular':
                self.ode_dis_model = self.integrator_eular(self.ode_func ,t ,x ,u, p, T)
                self.ode_dis_func = ca.Function("ode_dis_func", [t, x, u, p], [self.ode_dis_model])
            elif self.opt['integrator'] == 'RK4':
                self.ode_dis_model = self.integrator_rk4(self.ode_func, t, x, u, p, T)
                self.ode_dis_func = ca.Function("ode_dis_func",[t, x, u, p],[self.ode_dis_model])
            else:
                print("No such an integrator")
        elif self.opt['cont_or_dis'] == 'dis':
            self.ode_dis_model = self.ode_func(t, x, u, p)
            self.ode_dis_func = self.ode_func       
        else:
            print("model type error")

        # Jacobian matrix of continuous system. Only time continuous system acquires jacobian of the continuous time system
        if self.opt['cont_or_dis'] == 'cont':
            self.jacobian_cont_x = ca.Function('jacobian_cont_x', [t, x, u, p],
                                                 [ca.jacobian(self.ode_cont_func(t, x, u, p), x)])
            self.jacobian_cont_u = ca.Function('jacobian_cont_u', [t, x, u, p],
                                                 [ca.jacobian(self.ode_cont_func(t, x, u, p), u)])
        # Jacobian matrix of discrete system
        self.jacobian_disc_x = ca.Function('jacobian_disc_x', [t, x, u, p],
                                             [ca.jacobian(self.ode_dis_func(t, x, u, p), x)])
        self.jacobian_disc_u = ca.Function('jacobian_disc_u', [t, x, u, p],
                                             [ca.jacobian(self.ode_dis_func(t, x, u, p), u)])

        # Define the integral function of the stage cost and terminal cost.
        if self.opt['cont_or_dis'] == 'cont':
            self.stage_cost_cont = self.stage_cost_func(x, xr, u, ur)
            self.stage_cost_cont_func = self.stage_cost_func
            
            self.stage_cost_dis = self.integrator_stage_cost(self.ode_cont_func, self.stage_cost_cont_func, t, x, xr, u, ur, p, delta_t)
            self.stage_cost_dis_func = ca.Function("stage_cost_dis_func", [x, xr, u, ur], [self.stage_cost_dis])
        elif self.opt['cont_or_dis'] == 'dis':
            self.stage_cost_dis = self.stage_cost_func(x, xr, u, ur)
            self.stage_cost_dis_func = self.stage_cost_func
        else:
            print("model type error")

        self.terminal_cost = self.terminal_cost_func(x, xr)
        
    
    def integrator_stage_cost(self, f, l, t, x, xr, u, ur, p, delta_t):
        '''
        This function calculates the integration of stage cost with RK4.
        '''
    
        k1 = f(t, x, u, p)
        k2 = f(t + delta_t / 2, x + delta_t / 2 * k1, u, p)
        k3 = f(t + delta_t / 2, x + delta_t / 2 * k2, u, p)
        k4 = f(t + delta_t, x + delta_t * k3, u, p)

        Q = 0
        k1_q = l(x, xr, u, ur)
        k2_q = l(x + delta_t / 2 * k1, xr, u, ur) 
        k3_q = l(x + delta_t / 2 * k2, xr, u, ur)
        k4_q = l(x + delta_t * k3, xr, u, ur)
        Q = Q + delta_t/6*(k1_q + 2*k2_q + 2*k3_q + k4_q)
        return Q
    
    

    def integrator_eular(self, f, t, x, u, p, delta_t):
        """
        Explicit Eular solver using casadi.

        Args:
            f: First order ODE in casadi function (Nx + Nt -> Nx).
            t: Current time.
            x: Current value. 
            u: Current input.
            delta_t: Step length.
        Returns:
            x_next: Vector of next value in casadi DM
        """
        k1= f(t, x, u, p)
        x_next = x + delta_t * k1
        
        return x_euler

    def integrator_rk4(self, f, t, x, u, p, delta_t):
        """
        Runge-Kutta 4th order solver using casadi.

        Args:
            f: First order ODE in casadi function (Nx + Nt -> Nx).
            t: Current time.
            x: Current value. 
            u: Current input.
            delta_t: Step length.
        Returns:
            x_next: Vector of next value in casadi DM
        """
        k1 = f(t, x, u, p)
        k2 = f(t + delta_t / 2, x + delta_t / 2 * k1, u, p)
        k3 = f(t + delta_t / 2, x + delta_t / 2 * k2, u, p)
        k4 = f(t + delta_t, x + delta_t * k3, u, p)
        x_next = x + delta_t / 6 * (k1 + 2 * k2 + 2 * k3 + k4)

        return x_next

    def sampling_time(self):
        """
        Get the sampling time
        """
        return self.T


    def model_shape(self):
        """
        Get the shape of the state, input, and parameters.

        return:
                Nx: Number of states
                Nu: Number of inputs
                Np: Number of parameters
        """
        return self.Nx, self.Nu, self.Np

    def get_continuous_model(self):
        return self.ode_cont_model

    def get_discrete_model(self):
        return self.ode_dis_model

    def get_continuous_func(self):
        return self.ode_cont_func

    def get_discrete_func(self):
        return self.ode_dis_func

    def get_continuous_stage_cost(self):
        return self.stage_cost_cont

    def get_discrete_stage_cost(self):
        return self.stage_cost_dis

    def get_continuous_stage_cost_func(self):
        return self.stage_cost_cont_func

    def get_discrete_stage_cost_func(self):
        return self.stage_cost_dis_func
    
    def get_terminal_cost(self):
        return self.terminal_cost

    def get_terminal_cost_func(self):
        return self.terminal_cost_func
    
    
    
    def get_model_parameter(self):
        return self.p

#     def get_continuous_model_fric_func(self):
#         return self.ode_fric_func

#     def get_discrete_model_fric_func(self):
#         return self.discrete_model_fric_func